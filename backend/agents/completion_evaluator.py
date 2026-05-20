"""
CompletionEvaluator: lets the agent decide *when to stop* instead of
counting steps.

Design rationale
----------------
A hard MAX_STEPS counter is a safety net, not a stop signal.  The model
should reason: "do I have enough information to answer this task well?"
That judgement is itself a language-model task — so we use a small,
temperature-0 LLM call after each tool round.

The evaluator is kept entirely separate from BaseAgent so it can be:
  - swapped out (rule-based, learned, etc.)
  - injected or omitted per agent type
  - tested in isolation

Cost note
---------
Each evaluation adds one extra LLM call.  We mitigate this by:
  1. Skipping the evaluation on step 0 (too early to judge).
  2. Using a short, token-efficient prompt.
  3. Stopping as soon as confidence >= threshold.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ToolCallSummary:
    """Compact record of one tool invocation for the evaluator."""
    tool: str
    result_preview: str      # first 300 chars of the tool result


@dataclass
class EvalContext:
    """Everything the evaluator needs to decide whether to stop."""
    task: str
    steps_taken: int
    max_steps: int
    tool_calls: list[ToolCallSummary] = field(default_factory=list)


@dataclass
class StopDecision:
    should_stop: bool
    confidence: float        # 0.0 – 1.0
    reason: str
    missing: str | None = None   # what is still needed (None if should_stop)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are a task-completion evaluator for an AI agent.

Your job: decide whether the agent has gathered enough information to
produce a high-quality answer to the user's task.

Output ONLY valid JSON — no markdown, no extra text:
{
  "should_stop": true | false,
  "confidence": <float 0.0–1.0>,
  "reason": "<one sentence>",
  "missing": "<what is still needed, or null if should_stop is true>"
}

Guidelines
----------
• should_stop = true  → the core task is directly addressable from what
  the agent already found; more calls would be redundant.
• should_stop = false → important information the task requires is still
  absent or too superficial.
• confidence reflects certainty of your judgement (not answer quality).
• Be progressively more willing to stop as steps_taken approaches
  max_steps — at the last step always return should_stop = true.
"""


def _build_user_message(ctx: EvalContext) -> str:
    calls_text = "\n".join(
        f"  [{i+1}] {s.tool}: {s.result_preview}"
        for i, s in enumerate(ctx.tool_calls)
    ) or "  (none yet)"

    return (
        f"Task: {ctx.task}\n\n"
        f"Steps taken: {ctx.steps_taken} / {ctx.max_steps}\n\n"
        f"Tool calls and results so far:\n{calls_text}"
    )


# ---------------------------------------------------------------------------
# CompletionEvaluator
# ---------------------------------------------------------------------------

class CompletionEvaluator:
    """
    Calls the LLM to evaluate whether the agent should stop searching
    and move to the final-answer phase.

    Parameters
    ----------
    client              AsyncOpenAI-compatible client.
    model               Model for evaluation (same model is fine; use
                        temperature=0 for determinism).
    confidence_threshold  Minimum confidence to honour a should_stop=True
                        decision.  Default 0.7 avoids premature stopping.
    skip_first_steps    Don't evaluate until this many steps have run.
                        Avoids wasting a call when the agent has barely
                        started.  Default 1.
    """

    def __init__(
        self,
        client: "AsyncOpenAI",
        model: str,
        *,
        confidence_threshold: float = 0.7,
        skip_first_steps: int = 1,
    ) -> None:
        self._client = client
        self._model = model
        self.confidence_threshold = confidence_threshold
        self.skip_first_steps = skip_first_steps

    async def evaluate(self, ctx: EvalContext) -> StopDecision:
        """
        Return a StopDecision for the given EvalContext.

        Always returns should_stop=True on the last step regardless of
        LLM output (hard safety net).

        If the LLM call fails, defaults to should_stop=False so the
        agent continues rather than halting incorrectly.
        """
        # Hard rule: must stop on last step
        if ctx.steps_taken >= ctx.max_steps:
            return StopDecision(
                should_stop=True,
                confidence=1.0,
                reason=f"Reached maximum steps ({ctx.max_steps}).",
            )

        # Skip early steps — not enough signal yet
        if ctx.steps_taken <= self.skip_first_steps:
            return StopDecision(
                should_stop=False,
                confidence=1.0,
                reason=f"Too early to evaluate (step {ctx.steps_taken}).",
                missing="Need more information before judging completeness.",
            )

        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _build_user_message(ctx)},
                ],
                temperature=0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or "{}"
            data = json.loads(raw)

            decision = StopDecision(
                should_stop=bool(data.get("should_stop", False)),
                confidence=float(data.get("confidence", 0.5)),
                reason=str(data.get("reason", "")),
                missing=data.get("missing") or None,
            )

            # Respect confidence threshold
            if decision.should_stop and decision.confidence < self.confidence_threshold:
                logger.debug(
                    "[evaluator] should_stop=True but confidence %.2f < threshold %.2f — continuing",
                    decision.confidence, self.confidence_threshold,
                )
                decision.should_stop = False

            logger.info(
                "[evaluator] step=%d should_stop=%s confidence=%.2f reason=%r",
                ctx.steps_taken, decision.should_stop, decision.confidence, decision.reason,
            )
            return decision

        except Exception as exc:
            logger.warning("[evaluator] LLM call failed: %s — defaulting to continue", exc)
            return StopDecision(
                should_stop=False,
                confidence=0.0,
                reason="Evaluator failed; defaulting to continue.",
                missing="Unknown — evaluation error.",
            )
