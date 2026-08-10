"""DeepResearchOrchestrator: 融合 DeepResearch 项目的「自进化 + 对抗降噪」循环。

流程
----
  Phase 1  write_research_brief   — 把用户任务转成结构化研究简报
  Phase 2  write_draft_report     — 基于简报生成报告初稿
  Phase 3  supervisor loop        — 多步降噪:
            iteration N:
              supervisor LLM (with tools: think/conduct/refine/complete)
              -> think_tool     : 反思
              -> ConductResearch : 并行派发 SubResearcher (KB/Tavily/Hybrid)
              -> refine_draft_report: 精修报告 -> evaluator 评分 -> red_team 对抗
              -> ResearchComplete : 终止
  Phase 4  final_report_generation — 融合简报/笔记/初稿流式生成最终报告

SSE 事件协议(扩展兼容现有 AgentPanel)
----------------------------------------
保留:
  plan / agent_start / agent_done / sub_agent_tool / text / done / error
新增:
  iteration      : {iter, max}
  critique       : {author, concern}               红队对抗反馈
  eval_score     : {comprehensive, accuracy, coherence, average, reason}
                   LLM-as-Judge 三维评分(每次 refine 后触发)
  research_brief : {content}                       简报文本
  draft_update   : {content, iteration, avg_score} 报告草稿快照
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import TYPE_CHECKING, AsyncGenerator

from agents.deep_research.evaluator import EvaluationResult, evaluate_draft_quality
from agents.deep_research.budget import ResearchBudget, ResearchBudgetExceeded
from agents.deep_research.prompts import (
    CRITICAL_ADDRESS_PROMPT,
    DRAFT_REPORT_PROMPT,
    FINAL_REPORT_PROMPT,
    MULTI_STEP_DENOISE_PROMPT,
    REFINE_DRAFT_REPORT_PROMPT,
    RESEARCH_BRIEF_PROMPT,
)
from agents.deep_research.red_team import red_team_review
from agents.deep_research.sub_researcher import SubResearcher
from agents.deep_research.model_config import DeepResearchModels
from agents.deep_research.model_runtime import apply_role_options
from agents.deep_research.search_policy import SearchQualityPolicy
from agents.deep_research.evidence import Evidence, EvidenceLedger
from agents.deep_research.state import (
    Critique,
    CritiqueCategory,
    CritiqueSeverity,
    EvaluationSnapshot,
    ResearchNote,
    ResearchPhase,
    ResearchState,
    ResearchStatus,
)
from agents.deep_research.tool_runtime import ToolRuntime
from agents.deep_research.cancellation import await_with_cancel
from config import (
    DATA_PATH,
    DEEP_RESEARCH_LLM_TIMEOUT_SECONDS,
    DEEP_RESEARCH_MAX_CONCURRENT,
    DEEP_RESEARCH_MAX_ITERATIONS,
    DEEP_RESEARCH_MIN_REPAIR_SCORE,
    DEEP_RESEARCH_RED_TEAM_MAX,
)
from harness.retry import CircuitBreaker, RetryPolicy, async_retry

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


def _usage_int(usage, field: str) -> int:
    value = getattr(usage, field, 0) if usage is not None else 0
    return int(value) if isinstance(value, (int, float)) else 0


def _assistant_message_payload(message) -> dict:
    """Serialize an assistant response for a later model turn.

    Thinking-mode DeepSeek tool calls require reasoning_content to be sent
    back on subsequent turns. Non-thinking models simply omit the field.
    """
    payload: dict = {
        "role": "assistant",
        "content": message.content or "",
    }
    reasoning_content = getattr(message, "reasoning_content", None)
    if reasoning_content:
        payload["reasoning_content"] = reasoning_content
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in tool_calls
        ]
    return payload


def _append_missing_tool_responses(messages: list[dict], tool_calls: list) -> None:
    """Complete the tool-call block before the next assistant request.

    OpenAI-compatible APIs require every tool_call_id from one assistant turn
    to be answered by a tool message, with no user/system message interleaved.
    Known tools are answered by their handlers; this closes any unsupported or
    otherwise skipped call so a model naming variation cannot poison history.
    """
    if not tool_calls:
        return

    assistant_index = max(
        (i for i, message in enumerate(messages) if message.get("role") == "assistant"),
        default=-1,
    )
    responded_ids = {
        message.get("tool_call_id")
        for message in messages[assistant_index + 1:]
        if message.get("role") == "tool"
    }
    for tc in tool_calls:
        call_id = getattr(tc, "id", "")
        if not call_id or call_id in responded_ids:
            continue
        tool_name = getattr(getattr(tc, "function", None), "name", "unknown")
        logger.warning(
            "[DeepResearch] completing unhandled supervisor tool call: id=%s name=%s",
            call_id,
            tool_name,
        )
        messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": (
                f"Tool call '{tool_name}' was not executed because it is unsupported "
                "or the supervisor ended this iteration. Use one of the declared tools."
            ),
        })


# Supervisor 可调用的工具 schema(供 LLM function-calling)
_THINK_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "think_tool",
        "description": "用于对研究进展和决策进行策略反思的工具。每次研究后,使用此工具分析结果并系统地规划下一步行动。",
        "parameters": {
            "type": "object",
            "properties": {
                "reflection": {
                    "type": "string",
                    "description": "对研究进展、发现、存在的差距以及下一步行动的详细反思。",
                },
            },
            "required": ["reflection"],
        },
    },
}

_CONDUCT_RESEARCH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "ConductResearch",
        "description": "将研究任务委派给专门的子 Agent。子 Agent 可访问个人知识库或联网搜索(按配置)。",
        "parameters": {
            "type": "object",
            "properties": {
                "research_topic": {
                    "type": "string",
                    "description": "研究主题。每次委派的任务应该为单一主题, 并需详细描述(至少一个段落)。",
                },
            },
            "required": ["research_topic"],
        },
    },
}

_REFINE_DRAFT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "refine_draft_report",
        "description": "使用 ConductResearch 的发现完善报告草稿, 并触发评估与红队对抗。",
        "parameters": {"type": "object", "properties": {},},
    },
}

_RESEARCH_COMPLETE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "ResearchComplete",
        "description": "表示研究已完成,可以进入最终报告撰写阶段。",
        "parameters": {"type": "object", "properties": {}},
    },
}

_SUPERVISOR_TOOLS = [
    _THINK_TOOL_SCHEMA,
    _CONDUCT_RESEARCH_TOOL_SCHEMA,
    _REFINE_DRAFT_TOOL_SCHEMA,
    _RESEARCH_COMPLETE_TOOL_SCHEMA,
]


class DeepResearchOrchestrator:
    """融合 DeepResearch 项目的深度研究编排器。

    与现有 OrchestratorAgent(ResearchAgent→AnalysisAgent→WritingAgent 顺序链)共存,
    通过前端 quick/deep 模式开关选择。
    """

    def __init__(
        self,
        client: "AsyncOpenAI",
        model: str,
        *,
        models: DeepResearchModels | None = None,
        llm_timeout_seconds: float = DEEP_RESEARCH_LLM_TIMEOUT_SECONDS,
        checkpoint_store=None,
        policy: RetryPolicy | None = None,
        circuit: CircuitBreaker | None = None,
        budget: ResearchBudget | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.models = models or DeepResearchModels.from_env(model)
        self.llm_timeout_seconds = llm_timeout_seconds
        self.checkpoint_store = checkpoint_store
        self._policy = policy or RetryPolicy(max_attempts=3, base_delay=1.0)
        self._circuit = circuit
        self.budget = budget or ResearchBudget()
        self._cancel_event: asyncio.Event | None = None
        self._search_policy = SearchQualityPolicy()

        # 复用一个 SubResearcher 实例(无状态, 可并发调用)
        self._sub_researcher = SubResearcher(
            client,
            self.models.researcher_main,
            summarizer_model=self.models.researcher_summarizer,
            compressor_model=self.models.researcher_compressor,
            llm_timeout_seconds=self.llm_timeout_seconds,
            policy=self._policy,
            circuit=self._circuit,
            search_policy=self._search_policy,
            budget=self.budget,
        )

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    async def _llm(self, **kwargs):
        role = kwargs.pop("_role", "deep_research")
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
            label=f"DeepResearch/{role}",
        )
        usage = getattr(response, "usage", None)
        self.budget.charge_llm(
            role=role,
            model=str(kwargs.get("model", self.model)),
            input_tokens=_usage_int(usage, "prompt_tokens"),
            output_tokens=_usage_int(usage, "completion_tokens"),
        )
        return response

    async def _llm_json(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> dict:
        """JSON mode 调用, 解析失败时返回 {}。"""
        resp = await self._llm(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            _role="brief_writer",
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            return json.loads(raw)
        except Exception:
            logger.warning("[DeepResearch] json parse failed: %s", raw[:200])
            return {}

    async def _llm_stream(self, prompt: str, *, model: str):
        """流式生成最终报告, yield token chunks。"""
        request_options = apply_role_options({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5,
            "stream": True,
            "stream_options": {"include_usage": True},
        }, "final_writer")
        stream = await await_with_cancel(
            self.client.chat.completions.create(**request_options),
            timeout_seconds=self.llm_timeout_seconds,
            cancel_event=self._cancel_event,
        )
        iterator = stream.__aiter__()
        final_input_tokens = 0
        final_output_tokens = 0
        while True:
            try:
                chunk = await await_with_cancel(
                    anext(iterator),
                    timeout_seconds=self.llm_timeout_seconds,
                    cancel_event=self._cancel_event,
                )
            except StopAsyncIteration:
                break
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
            if chunk.usage:
                final_input_tokens = _usage_int(chunk.usage, "prompt_tokens")
                final_output_tokens = _usage_int(chunk.usage, "completion_tokens")
        self._last_final_input = final_input_tokens
        self._last_final_output = final_output_tokens
        self.budget.charge_llm(
            role="final_writer",
            model=model,
            input_tokens=final_input_tokens,
            output_tokens=final_output_tokens,
        )

    # ------------------------------------------------------------------
    # Checkpoint helpers
    # ------------------------------------------------------------------

    def _save_checkpoint(self, run_id: str, task: str, step: int, metadata: dict) -> None:
        if self.checkpoint_store is None:
            return
        from harness.checkpoint import Checkpoint
        cp = Checkpoint(run_id=run_id, task=task, step=step, history=[], metadata=metadata)
        self.checkpoint_store.save(cp)

    def _delete_checkpoint(self, run_id: str) -> None:
        if self.checkpoint_store is not None:
            self.checkpoint_store.delete(run_id)

    def _load_checkpoint(self, run_id: str) -> dict | None:
        if self.checkpoint_store is None:
            return None
        cp = self.checkpoint_store.load(run_id)
        return cp.metadata if cp else None

    # ------------------------------------------------------------------
    # Phase 1 & 2: 简报 + 初稿
    # ------------------------------------------------------------------

    async def _write_brief(self, task: str) -> str:
        import datetime as _dt
        prompt = RESEARCH_BRIEF_PROMPT.format(
            messages=task,
            date=_dt.date.today().isoformat(),
        )
        data = await self._llm_json(
            prompt, model=self.models.draft, temperature=0.1, max_tokens=2048
        )
        brief = str(data.get("research_brief", "")).strip()
        if not brief:
            brief = task  # 兜底
        return brief

    async def _write_draft(self, brief: str) -> str:
        import datetime as _dt
        prompt = DRAFT_REPORT_PROMPT.format(
            research_brief=brief,
            date=_dt.date.today().isoformat(),
        )
        # 报告正文可能很长。直接生成 Markdown，避免被 token 上限截断后形成
        # 不完整 JSON，继而触发一次无意义的重试和二次 LLM 调用。
        resp = await self._llm(
            model=self.models.draft,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=8192,
            _role="draft_writer",
        )
        return (resp.choices[0].message.content or brief).strip()

    async def _refine_draft(self, brief: str, findings: str, draft: str) -> str:
        import datetime as _dt
        prompt = REFINE_DRAFT_REPORT_PROMPT.format(
            research_brief=brief,
            findings=findings,
            draft_report=draft,
            date=_dt.date.today().isoformat(),
        )
        resp = await self._llm(
            model=self.models.writer,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=4096,
            _role="writer",
        )
        new_draft = resp.choices[0].message.content or draft
        return new_draft if new_draft.strip() else draft

    # ------------------------------------------------------------------
    # Phase 3: Supervisor step + parallel sub-researcher runner
    # ------------------------------------------------------------------

    async def _supervisor_step(
        self,
        messages: list[dict],
        *,
        needs_quality_repair: bool,
        unaddressed_critiques: list[str],
    ):
        """单次 supervisor LLM 调用, 返回 response。"""
        import datetime as _dt
        system_prompt = MULTI_STEP_DENOISE_PROMPT.format(
            date=_dt.date.today().isoformat(),
            max_concurrent_research_units=DEEP_RESEARCH_MAX_CONCURRENT,
            max_researcher_iterations=DEEP_RESEARCH_MAX_ITERATIONS,
        )
        full_messages: list[dict] = [
            {"role": "system", "content": system_prompt},
        ]
        if unaddressed_critiques:
            critique_text = "\n".join(f"- {c}" for c in unaddressed_critiques)
            full_messages.append({
                "role": "system",
                "content": CRITICAL_ADDRESS_PROMPT.format(critique_text=critique_text),
            })
        if needs_quality_repair:
            full_messages.append({
                "role": "system",
                "content": "上一稿报告质量较低(得分低于阈值),请继续完善。",
            })
        full_messages.extend(messages)

        return await self._llm(
            model=self.models.supervisor,
            messages=full_messages,
            tools=_SUPERVISOR_TOOLS,
            temperature=0.3,
            _role="supervisor",
        )

    async def _run_concurrent_sub_researchers(
        self,
        conduct_calls: list,
    ) -> AsyncGenerator[dict, None]:
        """并行派发多个 SubResearcher, 实时 yield 各自的事件 + 末尾的研究笔记。

        使用 asyncio.Queue + background tasks 实现: 每个 SubResearcher 把事件
        推入队列, 主协程从队列取出 yield。所有 SubResearcher 完成后, 主协程
        按调用顺序 yield 每个的研究笔记。
        """
        calls = conduct_calls
        concurrency_limit = max(1, DEEP_RESEARCH_MAX_CONCURRENT)
        semaphore = asyncio.Semaphore(concurrency_limit)
        queue: asyncio.Queue = asyncio.Queue()
        results: dict[int, str] = {}  # tc index -> research_note

        async def _runner(idx: int, tc):
            try:
                topic = ""
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    topic = args.get("research_topic", "")
                except Exception:
                    pass

                # 上限只约束同时运行的数量，不能截断 tool_calls。否则未执行的
                # tool_call_id 没有对应 ToolMessage，下一轮请求会被 API 拒绝。
                async with semaphore:
                    async for ev in self._sub_researcher.run_stream(topic):
                        await queue.put(ev)
                        if ev.get("type") == "sub_agent_done":
                            results[idx] = ev.get("result", "")
            except Exception as exc:
                if _is_content_risk_error(exc):
                    logger.warning(
                        "[DeepResearch] SubResearcher[%d] skipped provider-rejected content",
                        idx,
                    )
                    await queue.put({
                        "type": "phase_status",
                        "phase": "research_warning",
                        "label": "部分检索正文触发模型内容安全策略，已跳过并继续其他研究",
                    })
                    results[idx] = "(该子主题的检索正文被模型供应商安全策略拒绝，未据此形成结论。)"
                else:
                    logger.exception("[DeepResearch] SubResearcher[%d] failed", idx)
                    await queue.put({
                        "type": "error",
                        "message": f"SubResearcher 失败: {exc}",
                    })
                    results[idx] = f"(SubResearcher 失败: {exc})"
            # signal completion
            await queue.put({"__done__": idx})

        # 启动 background tasks
        tasks = [asyncio.create_task(_runner(i, tc)) for i, tc in enumerate(calls)]
        try:
            completed = 0
            while completed < len(calls):
                ev = await queue.get()
                if "__done__" in ev:
                    completed += 1
                    continue
                yield ev
        finally:
            # 取消未完成的 task(若主循环提前退出)
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        # 按原 conduct_calls 顺序产出 (tc, note) 事件, 让上层组装 ToolMessage
        for i, tc in enumerate(calls):
            yield {
                "type": "__sub_researcher_result__",
                "tool_call_id": tc.id,
                "result": results.get(i, ""),
            }

    async def _run_supervisor_loop(
        self,
        *,
        task: str,
        brief: str,
        draft: str,
        run_id: str,
        research_state: ResearchState | None = None,
        single_iteration: bool = False,
    ) -> AsyncGenerator[dict, None]:
        """执行 supervisor 多步降噪循环, yield 中间事件。"""
        state = research_state or ResearchState(
            run_id=run_id,
            task=task,
            brief=brief,
            draft=draft,
            status=ResearchStatus.RUNNING,
        )
        notes = [note.content for note in state.notes]
        critique_nums = len(state.critiques)
        active_critiques = [item.problem for item in state.open_critiques]
        needs_quality_repair = bool(
            state.latest_evaluation
            and state.latest_evaluation.average < DEEP_RESEARCH_MIN_REPAIR_SCORE
        )
        supervisor_messages = state.supervisor_messages or [
            {"role": "user", "content": f"Here is the draft report: {draft}"},
            {"role": "user", "content": brief},
        ]
        evidence_ledger = EvidenceLedger(state.evidence)
        start_iteration = state.iteration + 1
        final_iteration = (
            start_iteration if single_iteration else DEEP_RESEARCH_MAX_ITERATIONS
        )

        for iteration in range(start_iteration, final_iteration + 1):
            state.iteration = iteration
            state.phase = ResearchPhase.RESEARCHING
            # ── 迭代开始 ──────────────────────────────────────────────
            yield {
                "type": "iteration",
                "iter": iteration,
                "max": DEEP_RESEARCH_MAX_ITERATIONS,
            }
            yield {
                "type": "phase_status",
                "phase": "supervisor_thinking",
                "label": "Supervisor 正在规划下一步",
                "iteration": iteration,
            }

            try:
                resp = await self._supervisor_step(
                    supervisor_messages,
                    needs_quality_repair=needs_quality_repair,
                    unaddressed_critiques=active_critiques,
                )
            except Exception as exc:
                logger.warning(
                    "[DeepResearch] supervisor unavailable (%s); finalizing best draft",
                    type(exc).__name__,
                )
                state.stop_reason = f"provider_unavailable: Supervisor {type(exc).__name__}"
                yield {
                    "type": "phase_status",
                    "phase": "research_warning",
                    "label": "Supervisor 连接暂时不可用，正在使用当前最佳草稿完成报告",
                    "iteration": iteration,
                }
                break

            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []

            # 工具的调度可自定义（ConductResearch 仍保持批量并发），但整个
            # assistant + ToolMessage block 最终由 ToolRuntime 原子组装。
            tool_responses: dict[str, str] = {}

            # 终止条件: 无 tool_calls 或调用 ResearchComplete 或达上限
            is_complete = any(tc.function.name == "ResearchComplete" for tc in tool_calls)
            if not tool_calls or is_complete:
                turn = ToolRuntime().assemble_turn(msg, tool_responses, usage=getattr(resp, "usage", None))
                supervisor_messages.extend(turn.messages)
                for result in turn.results:
                    self.budget.charge_tool(result.name)
                logger.info(
                    "[DeepResearch] supervisor terminated at iter=%d (complete=%s)",
                    iteration, is_complete,
                )
                yield {
                    "type": "sub_agent_tool",
                    "agent": "Supervisor",
                    "tool": "ResearchComplete" if is_complete else "natural_stop",
                    "label": "研究完成" if is_complete else "自然停止",
                    "args": "",
                }
                state.supervisor_requested_complete = True
                break

            # ── 执行工具调用 ──────────────────────────────────────────
            think_calls = [tc for tc in tool_calls if tc.function.name == "think_tool"]
            conduct_calls = [tc for tc in tool_calls if tc.function.name == "ConductResearch"]
            refine_calls = [tc for tc in tool_calls if tc.function.name == "refine_draft_report"]

            # (a) think_tool — 同步记录反思
            for tc in think_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                yield {
                    "type": "sub_agent_tool",
                    "agent": "Supervisor",
                    "tool": "think_tool",
                    "label": "思考",
                    "args": tc.function.arguments,
                }
                tool_responses[tc.id] = f"Reflection recorded: {args.get('reflection', '')}"

            # (b) ConductResearch — 并行派发 SubResearcher, 实时透传事件
            if conduct_calls:
                yield {
                    "type": "phase_status",
                    "phase": "searching",
                    "label": "正在并行检索最新资料",
                    "iteration": iteration,
                }
                yield {
                    "type": "agent_start",
                    "agent": "SubResearcher",
                    "task": (
                        f"派发 {len(conduct_calls)} 个子研究主题"
                        f"（最大并发 {DEEP_RESEARCH_MAX_CONCURRENT}）"
                    ),
                }

                async for ev in self._run_concurrent_sub_researchers(conduct_calls):
                    if ev.get("type") == "__sub_researcher_result__":
                        note = ev.get("result", "")
                        notes.append(note)
                        tool_responses[ev.get("tool_call_id", "")] = note
                        state.notes.append(ResearchNote(
                            topic="Supervisor delegated research",
                            content=note,
                            iteration=iteration,
                        ))
                    else:
                        if ev.get("type") == "research_source" and ev.get("evidence"):
                            evidence_ledger.add(Evidence.from_dict(ev["evidence"]))
                        yield ev

                yield {
                    "type": "agent_done",
                    "agent": "SubResearcher",
                    "summary": (notes[-1] if notes else "")[:300] + ("…" if notes and len(notes[-1]) > 300 else ""),
                    "stop_reason": f"第 {iteration} 轮并行研究完成",
                }

            # (c) refine_draft_report — 精修 + 评分 + 红队
            for tc in refine_calls:
                yield {
                    "type": "phase_status",
                    "phase": "summarizing",
                    "label": "正在汇总证据并修订报告",
                    "iteration": iteration,
                }
                findings = "\n".join(notes) if notes else "(暂无研究发现)"
                new_draft = await self._refine_draft(brief, findings, draft)
                draft = new_draft

                # 评估 — self-evolution
                eval_result: EvaluationResult = await evaluate_draft_quality(
                    self.client,
                    self.models.evaluator,
                    research_brief=brief,
                    draft_report=new_draft,
                    evidence=evidence_ledger.values(),
                    policy=self._policy,
                    circuit=self._circuit,
                    timeout_seconds=self.llm_timeout_seconds,
                    budget=self.budget,
                )
                yield {
                    "type": "eval_score",
                    "comprehensive": eval_result.comprehensiveness_score,
                    "accuracy": eval_result.accuracy_score,
                    "coherence": eval_result.coherence_score,
                    "average": round(eval_result.average, 2),
                    "reason": eval_result.reason,
                    "iteration": iteration,
                }
                coverage = eval_result.evidence_coverage
                state.evaluations.append(EvaluationSnapshot(
                    iteration=iteration,
                    comprehensiveness_score=eval_result.comprehensiveness_score,
                    accuracy_score=eval_result.accuracy_score,
                    coherence_score=eval_result.coherence_score,
                    evidence_coverage=coverage,
                    evidence_count=len(evidence_ledger),
                    reason=eval_result.reason,
                ))

                # 红队对抗
                red_team_executed = True
                try:
                    critique_findings = await red_team_review(
                        self.client,
                        self.models.red_team,
                        research_brief=brief,
                        draft_report=new_draft,
                        evidence=evidence_ledger.values(),
                        critique_nums=critique_nums,
                        policy=self._policy,
                        circuit=self._circuit,
                        timeout_seconds=self.llm_timeout_seconds,
                        budget=self.budget,
                        iteration=iteration,
                    )
                except ResearchBudgetExceeded:
                    raise
                except Exception as exc:
                    red_team_executed = False
                    critique_findings = []
                    logger.warning(
                        "[DeepResearch] Red Team unavailable (%s); preserving open critiques",
                        type(exc).__name__,
                    )
                    yield {
                        "type": "phase_status",
                        "phase": "research_warning",
                        "label": "Red Team 暂时不可用，已保留现有批评并继续生成报告",
                        "iteration": iteration,
                    }
                if critique_findings:
                    critique_nums += 1
                    for finding in critique_findings:
                        active_critiques.append(finding.problem)
                        state.add_critique(finding)
                        yield {
                            "type": "critique",
                            "author": "Red Team Adversary",
                            "concern": finding.problem,
                            "category": finding.category.value,
                            "severity": finding.severity.value,
                            "critique_id": finding.critique_id,
                            "evidence_ids": finding.evidence_ids,
                            "remediation": finding.remediation,
                            "status": finding.status.value,
                            "iteration": iteration,
                        }
                else:
                    # 达到审查预算不是 PASS；只有仍实际执行了红队复核时，
                    # 才能关闭上一轮 Critique。
                    if (
                        red_team_executed
                        and critique_nums < DEEP_RESEARCH_RED_TEAM_MAX
                        and len(new_draft) >= 50
                    ):
                        active_critiques = []
                        for open_critique in list(state.open_critiques):
                            state.resolve_critique(
                                open_critique.critique_id,
                                "修订后 Red Team 复核通过",
                            )

                # 报告草稿快照
                yield {
                    "type": "draft_update",
                    "content": new_draft,
                    "iteration": iteration,
                    "avg_score": round(eval_result.average, 2),
                }

                needs_quality_repair = eval_result.average < DEEP_RESEARCH_MIN_REPAIR_SCORE

                tool_responses[tc.id] = (
                        f"Draft Updated.\nQuality Score: {eval_result.average:.2f}/10.\n"
                        f"Judge Feedback: {eval_result.reason}"
                    )

            turn = ToolRuntime().assemble_turn(
                msg,
                tool_responses,
                usage=getattr(resp, "usage", None),
            )
            supervisor_messages.extend(turn.messages)
            for result in turn.results:
                self.budget.charge_tool(result.name)
            state.brief = brief
            state.draft = draft
            state.evidence = evidence_ledger.values()
            state.supervisor_messages = supervisor_messages
            state.usage = self.budget.usage
            state.touch()

            # 检查点保存
            self._save_checkpoint(run_id, task, step=iteration, metadata={
                "iteration": iteration,
                "research_brief": brief,
                "draft_report": draft,
                "notes_count": len(notes),
            })

        # 末态: 同步完整 ResearchState，供 LangGraph Checkpointer 持久化。
        state.brief = brief
        state.draft = draft
        state.evidence = evidence_ledger.values()
        state.supervisor_messages = supervisor_messages
        state.usage = self.budget.usage
        state.touch()
        yield {
            "type": "__supervisor_final__",
            "draft": draft,
            "notes": notes,
            "state": state,
        }

    # ------------------------------------------------------------------
    # Phase 4: 最终报告
    # ------------------------------------------------------------------

    async def _final_report_stream(self, brief: str, notes: list[str], draft: str):
        import datetime as _dt
        findings = "\n".join(notes) if notes else draft
        prompt = FINAL_REPORT_PROMPT.format(
            research_brief=brief,
            findings=findings,
            date=_dt.date.today().isoformat(),
            draft_report=draft,
        )
        async for delta in self._llm_stream(prompt, model=self.models.writer):
            yield delta

    # ------------------------------------------------------------------
    # 主入口 run_stream
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        task: str,
        *,
        run_id: str | None = None,
        lesson_context: str = "",
        cancel_event: asyncio.Event | None = None,
        use_langgraph: bool = True,
    ) -> AsyncGenerator[dict, None]:
        """主流程: 简报 → 初稿 → supervisor 循环 → 最终报告。"""
        run_id = run_id or str(uuid.uuid4())
        from agent_skills.loader import FileSkillRegistry

        skill_context = FileSkillRegistry().prompt_for(task)
        enriched_task = "\n\n".join(
            part for part in (lesson_context, skill_context, task) if part
        )

        if use_langgraph:
            from agents.deep_research.graph_runtime import DeepResearchGraphRuntime

            self._cancel_event = cancel_event
            self._sub_researcher._cancel_event = cancel_event
            runtime = DeepResearchGraphRuntime(
                self,
                checkpoint_path=DATA_PATH / "deep_research_checkpoints.sqlite",
                cancel_event=cancel_event,
            )
            async for event in runtime.run_stream(enriched_task, run_id=run_id):
                yield event
            return

        # ── Phase 1: 简报 ──────────────────────────────────────────────
        plan_steps = [
            {"agent": "BriefWriter",  "task": "生成研究简报",       "status": "pending"},
            {"agent": "DraftWriter",  "task": "生成报告初稿",       "status": "pending"},
            {"agent": "Supervisor",   "task": "多步降噪循环",       "status": "pending"},
            {"agent": "FinalWriter",  "task": "撰写最终报告",       "status": "pending"},
        ]
        yield {"type": "plan", "steps": plan_steps}

        yield {"type": "agent_start", "agent": "BriefWriter", "task": "生成研究简报"}
        brief = await self._write_brief(enriched_task)
        yield {"type": "research_brief", "content": brief}
        yield {
            "type": "agent_done",
            "agent": "BriefWriter",
            "summary": brief[:300] + ("…" if len(brief) > 300 else ""),
            "stop_reason": "简报生成完成",
        }

        # ── Phase 2: 初稿 ──────────────────────────────────────────────
        yield {"type": "agent_start", "agent": "DraftWriter", "task": "基于简报撰写报告初稿"}
        draft = await self._write_draft(brief)
        yield {"type": "draft_update", "content": draft, "iteration": 0, "avg_score": None}
        yield {
            "type": "agent_done",
            "agent": "DraftWriter",
            "summary": draft[:300] + ("…" if len(draft) > 300 else ""),
            "stop_reason": "初稿生成完成",
        }

        # ── Phase 3: Supervisor 循环 ───────────────────────────────────
        yield {"type": "agent_start", "agent": "Supervisor", "task": "执行 think/conduct/refine 多步降噪循环"}

        final_draft = draft
        notes: list[str] = []
        final_evidence: list[Evidence] = []
        try:
            async for ev in self._run_supervisor_loop(
                task=enriched_task, brief=brief, draft=draft, run_id=run_id,
            ):
                if ev.get("type") == "__supervisor_final__":
                    final_draft = ev.get("draft", draft)
                    notes = ev.get("notes", []) or []
                    final_state = ev.get("state")
                    final_evidence = list(getattr(final_state, "evidence", []) or [])
                    continue
                yield ev
        except Exception as exc:
            yield {"type": "error", "message": f"supervisor loop failed: {exc}"}
            return

        yield {
            "type": "agent_done",
            "agent": "Supervisor",
            "summary": final_draft[:300] + ("…" if len(final_draft) > 300 else ""),
            "stop_reason": f"完成迭代上限或调用 ResearchComplete",
        }

        # ── Phase 4: 最终报告(流式) ────────────────────────────────────
        yield {
            "type": "phase_status",
            "phase": "finalizing",
            "label": "正在生成最终研究报告",
        }
        yield {"type": "agent_start", "agent": "FinalWriter", "task": "融合简报/笔记/初稿, 撰写最终报告"}

        final_text = ""
        async for delta in self._final_report_stream(brief, notes, final_draft):
            final_text += delta
            yield {"type": "text", "content": delta}

        from agents.deep_research.citation_validator import ensure_clickable_sources
        linked_report = ensure_clickable_sources(final_text, final_evidence)
        if linked_report != final_text:
            final_text = linked_report
            yield {"type": "report_replace", "content": final_text}

        yield {
            "type": "agent_done",
            "agent": "FinalWriter",
            "summary": final_text[:300] + ("…" if len(final_text) > 300 else ""),
            "stop_reason": "最终报告撰写完成",
        }

        self._delete_checkpoint(run_id)
        yield {"type": "done"}


def _is_content_risk_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if "content exists risk" in str(current).casefold():
            return True
        current = current.__cause__ or current.__context__
    return False
