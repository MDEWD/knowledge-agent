"""
BaseAgent: foundation for all sub-agents.

Stop condition
--------------
The loop terminates when ANY of these is true (checked in order):

  1. The LLM stops calling tools naturally (finish_reason != "tool_calls").
     This is the primary, preferred signal.

  2. CompletionEvaluator decides the task is done (should_stop=True,
     confidence >= threshold).  Evaluated after each tool round starting
     from step 1.

  3. MAX_STEPS hard limit is reached.  Safety net only — should rarely
     fire if the evaluator is working correctly.

Streaming
---------
run_stream() is the primary implementation; it yields dict events so the
orchestrator can forward them to the frontend in real time.  run() is a
thin wrapper that collects the final result from run_stream().

LLM resilience
--------------
Every LLM call is wrapped with async_retry so transient API errors (rate
limits, 5xx, network timeouts) are retried with exponential back-off.  An
optional CircuitBreaker can be shared across agents to fast-fail when the
upstream is known to be down.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, AsyncGenerator

if TYPE_CHECKING:
    from openai import AsyncOpenAI

from agents.completion_evaluator import (
    CompletionEvaluator,
    EvalContext,
    StopDecision,
    ToolCallSummary,
)
from harness.retry import CircuitBreaker, RetryPolicy, async_retry

logger = logging.getLogger(__name__)

MAX_STEPS = 8
_FORCE_ANSWER_PROMPT = (
    "根据以上已收集的信息，请直接给出最终答案。不要再调用工具。"
)

# Human-readable labels for tool names (used in streaming events)
_TOOL_LABELS: dict[str, str] = {
    "search_knowledge_base": "搜索知识库",
    "list_videos_in_kb": "列出知识库内容",
    "get_video_note": "读取笔记",
    "compare_videos": "对比视频",
    "summarize_category": "汇总分类",
    "request_additional_research": "请求补充研究",
}


class BaseAgent:
    name: str = "BaseAgent"
    description: str = ""
    system_prompt: str = ""
    tools: list[dict] = []

    def __init__(
        self,
        client: "AsyncOpenAI",
        model: str,
        *,
        evaluator: CompletionEvaluator | None = None,
        policy: RetryPolicy | None = None,
        circuit: CircuitBreaker | None = None,
    ):
        self.client = client
        self.model = model
        self.evaluator = evaluator
        self._policy = policy or RetryPolicy(max_attempts=3, base_delay=1.0)
        self._circuit = circuit

    async def _llm(self, **kwargs):
        """Wrap every LLM call with retry + circuit breaking."""
        async def _call():
            return await self.client.chat.completions.create(**kwargs)

        return await async_retry(
            _call,
            policy=self._policy,
            circuit=self._circuit,
            label=f"{self.name}/llm",
        )

    async def _execute_tool(self, tool_name: str, arguments: str) -> str:
        """Override in subclasses to implement tool logic."""
        return f"[{tool_name}] not implemented"

    async def _request_final_answer(
        self, messages: list[dict], stop_decision: StopDecision | None = None
    ) -> str:
        hint = ""
        if stop_decision:
            hint = f"（判断依据：{stop_decision.reason}）"
        messages.append({
            "role": "user",
            "content": _FORCE_ANSWER_PROMPT + hint,
        })
        resp = await self._llm(
            model=self.model,
            messages=messages,
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""

    async def run_stream(
        self, task: str, context: str = ""
    ) -> AsyncGenerator[dict, None]:
        """
        Execute the task using a ReAct loop, yielding events as they happen.

        Yields
        ------
        {"type": "sub_agent_tool",  "agent": name, "tool": "...", "label": "..."}
            Emitted before each tool call so the orchestrator can forward it to
            the frontend for real-time transparency.

        {"type": "sub_agent_done",  "agent": name, "result": "...",
         "stop_reason": str | None, "stop_confidence": float | None}
            Emitted exactly once, at the end of the loop.
        """
        messages: list[dict] = [{"role": "system", "content": self.system_prompt}]
        if context:
            messages.append({"role": "user", "content": f"背景信息：\n{context}"})
        messages.append({"role": "user", "content": task})

        all_tool_calls: list[ToolCallSummary] = []

        for step in range(MAX_STEPS):
            resp = await self._llm(
                model=self.model,
                messages=messages,
                tools=self.tools if self.tools else None,
                temperature=0.3,
            )
            choice = resp.choices[0]
            msg = choice.message

            # ── 1. Natural stop ───────────────────────────────────────────────
            if choice.finish_reason != "tool_calls" or not msg.tool_calls:
                logger.info("[%s] natural stop at step %d", self.name, step)
                yield {
                    "type": "sub_agent_done",
                    "agent": self.name,
                    "result": msg.content or "",
                    "stop_reason": None,
                    "stop_confidence": None,
                }
                return

            # ── 2. Execute tool calls ─────────────────────────────────────────
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                label = _TOOL_LABELS.get(tc.function.name, tc.function.name)
                yield {
                    "type": "sub_agent_tool",
                    "agent": self.name,
                    "tool": tc.function.name,
                    "label": label,
                    "args": tc.function.arguments,
                }

                result = await self._execute_tool(tc.function.name, tc.function.arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
                all_tool_calls.append(
                    ToolCallSummary(
                        tool=tc.function.name,
                        result_preview=result[:300],
                    )
                )

            # ── 3. Evaluator ──────────────────────────────────────────────────
            if self.evaluator is not None:
                ctx = EvalContext(
                    task=task,
                    steps_taken=step + 1,
                    max_steps=MAX_STEPS,
                    tool_calls=list(all_tool_calls),
                )
                decision = await self.evaluator.evaluate(ctx)

                if decision.should_stop:
                    logger.info(
                        "[%s] evaluator stopped at step %d: %s",
                        self.name, step + 1, decision.reason,
                    )
                    final = await self._request_final_answer(messages, decision)
                    yield {
                        "type": "sub_agent_done",
                        "agent": self.name,
                        "result": final,
                        "stop_reason": decision.reason,
                        "stop_confidence": decision.confidence,
                    }
                    return

        # ── 4. Hard MAX_STEPS ceiling ─────────────────────────────────────────
        logger.warning("[%s] hit MAX_STEPS=%d — forcing final answer", self.name, MAX_STEPS)
        final = await self._request_final_answer(messages)
        yield {
            "type": "sub_agent_done",
            "agent": self.name,
            "result": final,
            "stop_reason": f"Reached hard limit of {MAX_STEPS} steps.",
            "stop_confidence": 1.0,
        }

    async def run(self, task: str, context: str = "") -> tuple[str, StopDecision | None]:
        """
        Execute the task; return (result_text, final_stop_decision).

        Delegates to run_stream() and collects the sub_agent_done event.
        final_stop_decision is None when the LLM stopped naturally.
        """
        result = ""
        decision: StopDecision | None = None

        async for event in self.run_stream(task, context):
            if event["type"] == "sub_agent_done":
                result = event["result"]
                reason = event.get("stop_reason")
                conf = event.get("stop_confidence")
                if reason:
                    decision = StopDecision(
                        should_stop=True,
                        confidence=conf if conf is not None else 1.0,
                        reason=reason,
                    )

        return result, decision
