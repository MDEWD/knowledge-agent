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

LLM resilience
--------------
Every LLM call is wrapped with async_retry so transient API errors (rate
limits, 5xx, network timeouts) are retried with exponential back-off.  An
optional CircuitBreaker can be shared across agents to fast-fail when the
upstream is known to be down.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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
        """Wrapper that retries the LLM call according to the agent's policy."""
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

    async def run(self, task: str, context: str = "") -> tuple[str, StopDecision | None]:
        """
        Execute the task using a ReAct loop with intelligent stop detection.

        Returns
        -------
        (result_text, final_stop_decision)
        final_stop_decision is None when the LLM stopped naturally.
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

            # ── 1. Natural stop: LLM chose not to call any tool ───────────────
            if choice.finish_reason != "tool_calls" or not msg.tool_calls:
                logger.info("[%s] natural stop at step %d", self.name, step)
                return msg.content or "", None

            # ── 2. Execute tool calls ──────────────────────────────────────────
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

            # ── 3. Ask the evaluator whether we have enough ───────────────────
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
                    result = await self._request_final_answer(messages, decision)
                    return result, decision

        # ── 4. Hard MAX_STEPS ceiling ─────────────────────────────────────────
        logger.warning("[%s] hit MAX_STEPS=%d — forcing final answer", self.name, MAX_STEPS)
        result = await self._request_final_answer(messages)
        return result, StopDecision(
            should_stop=True,
            confidence=1.0,
            reason=f"Reached hard limit of {MAX_STEPS} steps.",
        )
