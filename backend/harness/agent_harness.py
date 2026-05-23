"""
AgentHarness — runtime infrastructure layer implementing Harness Engineering.

Harness Engineering (Mitchell Hashimoto, 2026):
    "Anytime an agent makes a mistake, engineer a solution so the
     agent will not make that mistake again in the future."

This harness wires together two layers:

  LEARNING LAYER (new)
    LessonStore     — accumulates every failure as a reusable lesson
    AgentContext    — injects relevant lessons into the agent's system
                      prompt so it starts informed, not naive

  EXECUTION LAYER (existing infrastructure)
    Guardrails      — pre/post safety checks with self-correction hints
    TokenBudget     — per-run resource limits
    CircuitBreaker  — fast-fail when downstream is degraded
    RetryPolicy     — exponential back-off for transient failures
    CheckpointStore — state persistence for resume-after-crash

Usage
-----
    harness = AgentHarness.default("data/")  # sensible defaults

    result = await harness.run(
        task="分析本周视频内容",
        agent_fn=my_agent.execute,   # async (system_prefix, task, history) → (str, list, dict)
    )
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .budget import BudgetExceededError, TokenBudget
from .checkpoint import Checkpoint, CheckpointStore
from .context import AgentContextBuilder
from .guardrails import Guardrails, GuardrailViolation
from .lessons import LessonStore
from .retry import CircuitBreaker, CircuitOpenError, RetryPolicy, async_retry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Run result
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """Returned by AgentHarness.run() on success."""
    run_id: str
    output: str
    steps_taken: int
    elapsed_seconds: float
    budget_summary: dict
    lessons_injected: int = 0
    resumed_from_step: int = 0


# ---------------------------------------------------------------------------
# AgentHarness
# ---------------------------------------------------------------------------

@dataclass
class AgentHarness:
    """
    Composes all Harness Engineering infrastructure for one agent.

    All fields are optional — pass only what you need.
    The lesson_store + context_builder pair is what makes this
    true Harness Engineering rather than just runtime middleware.
    """
    guardrails: Guardrails = field(default_factory=Guardrails)
    budget: TokenBudget = field(default_factory=TokenBudget)
    circuit: CircuitBreaker | None = None
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    checkpoint_store: CheckpointStore | None = None
    lesson_store: LessonStore | None = None
    context_builder: AgentContextBuilder | None = None

    # ------------------------------------------------------------------
    # Convenience constructor
    # ------------------------------------------------------------------

    @classmethod
    def default(cls, data_dir: str = "data") -> "AgentHarness":
        """
        Create a fully-wired harness with sensible defaults.
        Pass data_dir to control where lessons and checkpoints land.
        """
        store = LessonStore(f"{data_dir}/harness_lessons.json")
        return cls(
            guardrails=Guardrails(),
            budget=TokenBudget(
                max_input_tokens=80_000,
                max_output_tokens=20_000,
                max_tool_calls=30,
            ),
            circuit=CircuitBreaker(failure_threshold=5, recovery_timeout=60),
            policy=RetryPolicy(max_attempts=2),
            checkpoint_store=CheckpointStore(f"{data_dir}/checkpoints"),
            lesson_store=store,
            context_builder=AgentContextBuilder(store),
        )

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        task: str,
        agent_fn: Callable[
            [str, str, list[dict]],
            Awaitable[tuple[str, list[dict], dict]],
        ],
        *,
        run_id: str | None = None,
    ) -> RunResult:
        """
        Execute agent_fn under full harness protection.

        Parameters
        ----------
        task      : The top-level task string.
        agent_fn  : ``async (context_prefix, task, history) → (output, history, usage)``
                    context_prefix is the harness-generated system prompt prefix.
                    usage dict should have keys ``input_tokens`` and ``output_tokens``.
        run_id    : Stable identifier; auto-generated if omitted.

        Raises
        ------
        GuardrailViolation  : Input or output failed a safety check.
        BudgetExceededError : A token or call limit was crossed.
        CircuitOpenError    : The circuit breaker is open.
        Exception           : Last exception after all retries exhausted.
        """
        run_id = run_id or str(uuid.uuid4())
        started_at = time.monotonic()
        logger.info("[harness] run_id=%s task=%r", run_id, task[:80])

        # 1. Pre-check input
        self.guardrails.pre_check(task)

        # 2. Build context prefix from accumulated lessons
        context_prefix = ""
        lessons_injected = 0
        if self.context_builder:
            context_prefix = self.context_builder.build(task)
            if context_prefix:
                lessons = self.lesson_store.query(task) if self.lesson_store else []
                lessons_injected = len(lessons)
                logger.info(
                    "[harness] run_id=%s injecting %d lessons into context",
                    run_id, lessons_injected,
                )

        # 3. Attempt resume from checkpoint
        history: list[dict] = []
        resumed_from = 0
        if self.checkpoint_store:
            cp = self.checkpoint_store.load(run_id)
            if cp:
                history = cp.history
                resumed_from = cp.step
                logger.info("[harness] run_id=%s resuming from step %d", run_id, resumed_from)

        # 4. Execute with retry + circuit breaker
        step = resumed_from

        async def _call() -> tuple[str, list[dict], dict]:
            return await agent_fn(context_prefix, task, history)

        try:
            output, new_history, usage = await async_retry(
                _call,
                policy=self.policy,
                circuit=self.circuit,
                label=f"agent/{run_id}",
            )
        except Exception as exc:
            # Core harness engineering: record the failure as a lesson
            if self.lesson_store:
                fix_hint = _derive_fix_hint(exc)
                lesson = self.lesson_store.record(task, exc, fix_hint=fix_hint)
                logger.info(
                    "[harness] run_id=%s failure recorded as lesson %s",
                    run_id, lesson.id,
                )
            raise

        step += 1

        # 5. Charge budget
        self.budget.charge_input(usage.get("input_tokens", 0))
        self.budget.charge_output(usage.get("output_tokens", 0))
        self.budget.charge_tool_call()

        # 6. Post-check output
        try:
            self.guardrails.post_check(output)
        except GuardrailViolation as exc:
            if self.lesson_store:
                self.lesson_store.record(task, exc, fix_hint=str(exc))
            raise

        # 7. Clean up checkpoint on success
        if self.checkpoint_store:
            self.checkpoint_store.delete(run_id)

        elapsed = time.monotonic() - started_at
        logger.info(
            "[harness] run_id=%s done steps=%d elapsed=%.2fs lessons_injected=%d",
            run_id, step, elapsed, lessons_injected,
        )

        return RunResult(
            run_id=run_id,
            output=output,
            steps_taken=step,
            elapsed_seconds=elapsed,
            budget_summary=self.budget.summary(),
            lessons_injected=lessons_injected,
            resumed_from_step=resumed_from,
        )

    # ------------------------------------------------------------------
    # Step-level helpers
    # ------------------------------------------------------------------

    def save_step(self, run_id: str, task: str, step: int, history: list[dict]) -> None:
        """Persist a mid-run checkpoint.  No-op if no store is configured."""
        if self.checkpoint_store is None:
            return
        cp = Checkpoint(run_id=run_id, task=task, step=step, history=history)
        self.checkpoint_store.save(cp)

    def check_budget(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tool_call: bool = False,
    ) -> None:
        """Charge incremental usage mid-run.  Raises BudgetExceededError if exceeded."""
        if input_tokens:
            self.budget.charge_input(input_tokens)
        if output_tokens:
            self.budget.charge_output(output_tokens)
        if tool_call:
            self.budget.charge_tool_call()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_fix_hint(exc: Exception) -> str:
    """Generate a concrete fix hint based on exception type."""
    name = type(exc).__name__
    msg = str(exc)
    if "token" in msg.lower() or "budget" in name.lower():
        return "Reduce input size or break the task into smaller sub-tasks."
    if "circuit" in name.lower() or "open" in name.lower():
        return "Downstream service is degraded. Wait before retrying or use a fallback."
    if "timeout" in name.lower():
        return "Request timed out. Simplify the task or increase the timeout budget."
    if "guardrail" in name.lower():
        return msg  # guardrail violations already carry fix instructions
    return f"Caught {name}: {msg[:200]}. Review task scope and retry with adjusted input."
