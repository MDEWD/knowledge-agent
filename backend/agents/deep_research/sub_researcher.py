"""子研究 Agent: DeepResearch supervisor 的 ConductResearch 工具内层执行体。

每个子 Agent 拿到一个 research_topic, 在 ReAct 循环里调用检索工具(根据
SEARCH_BACKEND 路由 KB / Tavily / 混合), 最后把对话压缩成清洗过的研究笔记,
回传给 supervisor 作为一条 ToolMessage。

该模块直接复用 knowledge-agent 现有的 BaseAgent 风格: openai.AsyncOpenAI,
不依赖 langchain/langgraph。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, TYPE_CHECKING

from agents.deep_research.prompts import (
    COMPRESS_RESEARCH_HUMAN_PROMPT,
    COMPRESS_RESEARCH_SYSTEM_PROMPT,
    RESEARCH_AGENT_PROMPT,
)
from agents.deep_research.search_router import (
    execute_tool_call,
    get_sub_researcher_tools,
)
from agents.deep_research.search_policy import SearchQualityPolicy
from agents.deep_research.model_runtime import apply_role_options
from agents.deep_research.tool_runtime import ToolDefinition, ToolRuntime
from agents.deep_research.budget import ResearchBudget, ResearchBudgetExceeded
from agent_skills.loader import FileSkillRegistry
from agents.deep_research.cancellation import await_with_cancel
from config import DEEP_RESEARCH_SUB_MAX_STEPS
from config import DEEP_RESEARCH_LLM_TIMEOUT_SECONDS
from config import DEEP_RESEARCH_RESEARCHER_MAIN_API
from harness.retry import CircuitBreaker, RetryPolicy, async_retry

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_MAX_COMPRESS_TRANSCRIPT_CHARS = 60_000
_MAX_COMPRESS_MESSAGE_CHARS = 12_000

# 工具 chip 标签(供前端 sub_agent_tool 事件渲染)
_TOOL_LABELS: dict[str, str] = {
    "search_knowledge_base": "搜索知识库",
    "tavily_search": "联网搜索",
    "think_tool": "反思",
}


class SubResearcher:
    """单个研究主题的子 Agent。

    工具集与调用方式由 SEARCH_BACKEND 决定; ReAct 循环最多
    DEEP_RESEARCH_SUB_MAX_STEPS 步, 之后强制压缩返回。

    以 async generator 形式产出事件, 让 orchestrator 实时透传到 SSE。
    """

    def __init__(
        self,
        client: "AsyncOpenAI",
        model: str,
        *,
        summarizer_model: str | None = None,
        compressor_model: str | None = None,
        main_api: str = DEEP_RESEARCH_RESEARCHER_MAIN_API,
        llm_timeout_seconds: float = DEEP_RESEARCH_LLM_TIMEOUT_SECONDS,
        policy: RetryPolicy | None = None,
        circuit: CircuitBreaker | None = None,
        search_policy: SearchQualityPolicy | None = None,
        budget: ResearchBudget | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.summarizer_model = summarizer_model or model
        self.compressor_model = compressor_model or model
        self.main_api = _normalize_main_api(main_api)
        self.llm_timeout_seconds = llm_timeout_seconds
        self._policy = policy or RetryPolicy(max_attempts=3, base_delay=1.0)
        self._circuit = circuit
        self._search_policy = search_policy or SearchQualityPolicy()
        self.budget = budget or ResearchBudget()
        self._cancel_event: asyncio.Event | None = None
        self._tools, self._tool_names = get_sub_researcher_tools()

    # ------------------------------------------------------------------
    # LLM call wrapper
    # ------------------------------------------------------------------

    async def _llm(self, **kwargs):
        role = kwargs.pop("_role", "researcher")
        kwargs = apply_role_options(kwargs, role)
        async def _call():
            return await await_with_cancel(
                self.client.chat.completions.create(**kwargs),
                timeout_seconds=self.llm_timeout_seconds,
                cancel_event=self._cancel_event,
            )

        response = await async_retry(
            _call,
            policy=self._policy,
            circuit=self._circuit,
            label=f"SubResearcher/{role}",
        )
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage is not None else 0
        completion_tokens = getattr(usage, "completion_tokens", 0) if usage is not None else 0
        self.budget.charge_llm(
            role=role,
            model=str(kwargs.get("model", self.model)),
            input_tokens=int(prompt_tokens) if isinstance(prompt_tokens, (int, float)) else 0,
            output_tokens=int(completion_tokens) if isinstance(completion_tokens, (int, float)) else 0,
        )
        return response

    async def _responses_llm(self, **kwargs):
        """Call the stateless Responses API for researcher_main only."""

        role = kwargs.pop("_role", "researcher_main")
        # DeepSeek V4 enables thinking by default. Tool-oriented SubResearcher
        # calls favor latency and deterministic function calls, so disable it
        # using the Responses API control surface rather than Chat-only options.
        kwargs.setdefault("reasoning", {"effort": "none"})

        async def _call():
            responses = getattr(self.client, "responses", None)
            create = getattr(responses, "create", None)
            if not callable(create):
                raise RuntimeError(
                    "The configured OpenAI SDK/client does not expose "
                    "client.responses.create; install openai>=1.75 or set "
                    "DEEP_RESEARCH_RESEARCHER_MAIN_API=chat_completions"
                )
            return await await_with_cancel(
                create(**kwargs),
                timeout_seconds=self.llm_timeout_seconds,
                cancel_event=self._cancel_event,
            )

        response = await async_retry(
            _call,
            policy=self._policy,
            circuit=self._circuit,
            label=f"SubResearcher/{role}/responses",
        )
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) if usage is not None else 0
        output_tokens = getattr(usage, "output_tokens", 0) if usage is not None else 0
        self.budget.charge_llm(
            role=role,
            model=str(kwargs.get("model", self.model)),
            input_tokens=int(input_tokens) if isinstance(input_tokens, (int, float)) else 0,
            output_tokens=int(output_tokens) if isinstance(output_tokens, (int, float)) else 0,
        )
        return response

    async def _llm_text(self, prompt: str, *, temperature: float = 0.3) -> str:
        """单次文本 LLM 调用, 返回 content 字符串(供网页摘要等使用)。"""
        resp = await self._llm(
            model=self.summarizer_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            _role="researcher_summarizer",
        )
        return resp.choices[0].message.content or ""

    # ------------------------------------------------------------------
    # ReAct loop (async generator)
    # ------------------------------------------------------------------

    async def run_stream(self, research_topic: str) -> AsyncGenerator[dict, None]:
        """对 research_topic 做迭代检索, yield 中间事件, 末尾 yield 压缩结果。

        事件类型:
          {"type": "sub_agent_tool", "agent": "SubResearcher", "tool": ..., "label": ..., "args": ...}
          {"type": "sub_agent_done", "agent": "SubResearcher", "result": <压缩后的研究笔记>}
        """
        import datetime as _dt

        self._tools, self._tool_names = get_sub_researcher_tools(research_topic)
        system_prompt = RESEARCH_AGENT_PROMPT.format(date=_dt.date.today().isoformat())
        skill_context = FileSkillRegistry().prompt_for(research_topic)
        if skill_context:
            system_prompt += "\n\n匹配的项目 Agent Skills（必须遵守）：\n" + skill_context
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": research_topic},
        ]
        response_input: list[dict] = [
            {"role": "user", "content": research_topic},
        ]
        total_input_tokens = 0
        total_output_tokens = 0
        total_tool_calls = 0

        for step in range(DEEP_RESEARCH_SUB_MAX_STEPS):
            try:
                if self.main_api == "responses":
                    request: dict[str, Any] = {
                        "model": self.model,
                        "instructions": system_prompt,
                        # Pass an immutable turn snapshot to the SDK. The local
                        # stateless history is extended only after this request
                        # completes, so concurrent serialization cannot observe
                        # a partially assembled next turn.
                        "input": list(response_input),
                        "temperature": 0.3,
                        "_role": "researcher_main",
                    }
                    response_tools = self._responses_tool_schemas()
                    if response_tools:
                        request["tools"] = response_tools
                    resp = await self._responses_llm(**request)
                else:
                    resp = await self._llm(
                        model=self.model,
                        messages=messages,
                        tools=self._tools if self._tools else None,
                        temperature=0.3,
                        _role="researcher_main",
                    )
            except Exception as exc:
                if not _is_content_risk(exc):
                    raise
                logger.warning(
                    "[SubResearcher] provider rejected retrieved content; "
                    "retrying with tool payloads isolated"
                )
                messages = self._isolate_tool_payloads(messages)
                if self.main_api == "responses":
                    response_input = self._isolate_response_items(response_input)
                    request["input"] = list(response_input)
                    resp = await self._responses_llm(**request)
                else:
                    resp = await self._llm(
                        model=self.model,
                        messages=messages,
                        tools=self._tools if self._tools else None,
                        temperature=0.3,
                        _role="researcher_main",
                    )

            # ToolRuntime 原子生成 assistant + 连续完整 ToolMessage，避免任何
            # 分支遗漏 tool_call_id。工具事件通过 Queue 继续实时透传给 SSE。
            event_queue: asyncio.Queue[dict | None] = asyncio.Queue()

            def _handler(tool_name: str):
                async def execute(**arguments):
                    return await execute_tool_call(
                        tool_name,
                        arguments,
                        llm_call=self._llm_text,
                        event_sink=event_queue.put,
                        search_policy=self._search_policy,
                    )
                return execute

            definitions = {
                schema["function"]["name"]: ToolDefinition(
                    handler=_handler(schema["function"]["name"]),
                    parameters=schema["function"].get("parameters"),
                    timeout_seconds=self.llm_timeout_seconds,
                )
                for schema in self._tools
            }

            async def runtime_event(event: dict) -> None:
                if event.get("type") == "tool_start":
                    name = event.get("tool", "")
                    await event_queue.put({
                        "type": "sub_agent_tool",
                        "agent": "SubResearcher",
                        "tool": name,
                        "label": _TOOL_LABELS.get(name, name),
                        "args": event.get("arguments", "{}"),
                    })

            runtime = ToolRuntime(
                definitions,
                default_timeout_seconds=self.llm_timeout_seconds,
                event_sink=runtime_event,
            )

            async def execute_turn():
                try:
                    if self.main_api == "responses":
                        return await runtime.execute_response(resp)
                    msg = resp.choices[0].message
                    return await runtime.execute_turn(
                        msg, usage=getattr(resp, "usage", None)
                    )
                finally:
                    await event_queue.put(None)

            turn_task = asyncio.create_task(execute_turn())
            while True:
                streamed_event = await event_queue.get()
                if streamed_event is None:
                    break
                yield streamed_event
            turn = await turn_task
            messages.extend(turn.messages)
            if self.main_api == "responses":
                response_input.extend(turn.input_items)
            total_input_tokens += turn.usage.input_tokens
            total_output_tokens += turn.usage.output_tokens
            total_tool_calls += turn.usage.tool_calls
            for result in turn.results:
                self.budget.charge_tool(result.name)
            if turn.usage.tool_calls == 0:
                logger.info("[SubResearcher] natural stop at step %d", step)
                break

        # 压缩研究成果
        yield {
            "type": "phase_status",
            "phase": "summarizing",
            "label": "SubResearcher 正在压缩研究结果",
        }
        compressed = await self._compress(research_topic, messages)
        yield {
            "type": "sub_agent_done",
            "agent": "SubResearcher",
            "result": compressed,
            "usage": {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "tool_calls": total_tool_calls,
            },
        }

    async def run(self, research_topic: str) -> str:
        """便捷封装: 跑完整 run_stream, 返回压缩后的研究笔记字符串。"""
        result = ""
        async for event in self.run_stream(research_topic):
            if event["type"] == "sub_agent_done":
                result = event["result"]
        return result

    async def _compress(self, research_topic: str, messages: list[dict]) -> str:
        """把整个研究对话压缩成清洗后的研究笔记, 回传给 supervisor。"""
        import datetime as _dt

        system_prompt = COMPRESS_RESEARCH_SYSTEM_PROMPT.format(date=_dt.date.today().isoformat())
        transcript = self._format_transcript(messages)

        try:
            resp = await self._llm(
                model=self.compressor_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": transcript},
                    {"role": "user", "content": COMPRESS_RESEARCH_HUMAN_PROMPT.format(research_topic=research_topic)},
                ],
                temperature=0.2,
                _role="researcher_compressor",
            )
            compressed = resp.choices[0].message.content or ""
        except ResearchBudgetExceeded:
            raise
        except Exception as exc:
            logger.warning(
                "[SubResearcher] compression unavailable (%s); using bounded evidence fallback",
                type(exc).__name__,
            )
            fallback_messages = self._isolate_tool_payloads(messages) if _is_content_risk(exc) else messages
            return "[压缩模型暂时不可用，以下为保留的研究证据]\n\n" + self._fallback_evidence(fallback_messages)

        if not compressed.strip():
            # 兜底: 直接拼接所有 tool 结果
            compressed = "\n\n".join(
                m.get("content", "")
                for m in messages
                if m.get("role") == "tool"
            ) or "(空研究结果)"

        return compressed

    @staticmethod
    def _format_transcript(messages: list[dict]) -> str:
        """把最近且最相关的消息格式化为有硬上限的压缩输入。"""
        role_labels = {
            "system": "SYSTEM",
            "user": "USER",
            "assistant": "ASSISTANT",
            "tool": "TOOL_RESULT",
        }
        reverse_parts: list[str] = []
        remaining = _MAX_COMPRESS_TRANSCRIPT_CHARS
        for m in reversed(messages):
            role = role_labels.get(m.get("role", ""), m.get("role", "").upper())
            content = str(m.get("content", "") or "")[:_MAX_COMPRESS_MESSAGE_CHARS]
            block = f"=== {role} ===\n{content}"
            separator_cost = 2 if reverse_parts else 0
            available = remaining - separator_cost
            if available <= 0:
                break
            block = block[:available]
            reverse_parts.append(block)
            remaining -= len(block) + separator_cost
        return "\n\n".join(reversed(reverse_parts))

    @staticmethod
    def _fallback_evidence(messages: list[dict]) -> str:
        evidence = [m for m in messages if m.get("role") in {"tool", "assistant"}]
        return SubResearcher._format_transcript(evidence) or "(空研究结果)"

    @staticmethod
    def _isolate_tool_payloads(messages: list[dict]) -> list[dict]:
        isolated: list[dict] = []
        for message in messages:
            if message.get("role") != "tool":
                isolated.append(message)
                continue
            safe = dict(message)
            safe["content"] = (
                "[该工具正文触发模型供应商内容安全策略，已隔离。"
                "请改用其他来源继续研究，不得根据被隔离正文形成结论。]"
            )
            isolated.append(safe)
        return isolated

    def _responses_tool_schemas(self) -> list[dict[str, Any]]:
        """Convert Chat Completions tool schemas to Responses API schemas."""

        converted: list[dict[str, Any]] = []
        for schema in self._tools:
            function = schema.get("function") or {}
            item: dict[str, Any] = {
                "type": "function",
                "name": function.get("name", ""),
                "parameters": function.get("parameters") or {
                    "type": "object",
                    "properties": {},
                },
            }
            if function.get("description"):
                item["description"] = function["description"]
            converted.append(item)
        return converted

    @staticmethod
    def _isolate_response_items(items: list[dict]) -> list[dict]:
        """Remove rejected retrieved text while preserving tool-call pairing."""

        isolated: list[dict] = []
        for item in items:
            safe = dict(item)
            if safe.get("type") == "function_call_output":
                safe["output"] = (
                    "[该工具正文触发模型供应商内容安全策略，已隔离。"
                    "请改用其他来源继续研究，不得根据被隔离正文形成结论。]"
                )
            isolated.append(safe)
        return isolated


def _is_content_risk(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if "content exists risk" in str(current).casefold():
            return True
        current = current.__cause__ or current.__context__
    return False


def _normalize_main_api(value: str) -> str:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    if normalized in {"responses", "response"}:
        return "responses"
    if normalized in {"chat", "chat_completions", "completions"}:
        return "chat_completions"
    raise ValueError(
        "DEEP_RESEARCH_RESEARCHER_MAIN_API must be 'responses' or "
        "'chat_completions'"
    )
