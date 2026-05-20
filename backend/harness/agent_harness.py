"""
AgentHarness — the runtime infrastructure layer between the model brain and the world.

  Agent = Model + Harness

The harness wires together:
  - Guardrails      pre/post safety checks
  - TokenBudget     per-run resource limits
  - CircuitBreaker  fast-fail when a downstream service is degraded
  - RetryPolicy     exponential back-off for transient failures
  - CheckpointStore state persistence for resume-after-crash

Design goals
  1. The harness is *composable*: every component is optional.
  2. Run IDs flow through for end-to-end observability (LangFuse, logs).
  3. The harness is *transparent* to the model: it adds no agent-logic.
  4. All blocking I/O goes through async_retry; the harness stays async-native.

Usage:
    harness = AgentHarness(
        guardrails=Guardrails(),
        budget=TokenBudget(max_input=50_000, max_tool_calls=20),
        circuit=CircuitBreaker(failure_threshold=5, recovery_timeout=60),
        policy=RetryPolicy(max_attempts=3),
        checkpoint_store=CheckpointStore("data/checkpoints"),
    )

    result = await harness.run(
        run_id="abc123",
        task="分析本周视频内容",
        agent_fn=my_agent.execute,      # async callable(task, history) → str
    )
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncGenerator, Awaitable, Callable

from .budget import BudgetExceededError, TokenBudget
from .checkpoint import Checkpoint, CheckpointStore
from .guardrails import Guardrails, GuardrailViolation
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
    resumed_from_step: int = 0          # > 0 means the run was resumed


# ---------------------------------------------------------------------------
# AgentHarness
# ---------------------------------------------------------------------------

@dataclass
class AgentHarness:
    """
    Composes all safety and reliability infrastructure for one agent.

    All fields are optional — pass only what you need.
    """
    guardrails: Guardrails = field(default_factory=Guardrails)
    budget: TokenBudget = field(default_factory=TokenBudget)
    circuit: CircuitBreaker | None = None
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    checkpoint_store: CheckpointStore | None = None

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        task: str,
        agent_fn: Callable[[str, list[dict]], Awaitable[tuple[str, list[dict], dict]]],
        *,
        run_id: str | None = None,
    ) -> RunResult:
        """
        Execute agent_fn under full harness protection.

        Parameters
        ----------
        task      : The top-level task string.
        agent_fn  : ``async (task, history) → (output_str, new_history, usage_dict)``
                    where usage_dict has keys ``input_tokens`` and ``output_tokens``.
        run_id    : Stable identifier for this run; auto-generated if omitted.

        Returns
        -------
        RunResult with output, steps, elapsed time, and budget summary.

        Raises
        ------
        GuardrailViolation  : Input or output failed a safety check.
        BudgetExceededError : A token or call limit was crossed.
        CircuitOpenError    : The circuit breaker is open.
        Exception           : Last exception after all retry attempts exhausted.
        """
        run_id = run_id or str(uuid.uuid4())
        started_at = time.monotonic()

        logger.info("[harness] run_id=%s task=%r", run_id, task[:80])

        # 1. Pre-check input
        try:
            self.guardrails.pre_check(task)
        except GuardrailViolation:
            logger.warning("[harness] run_id=%s blocked by pre-check", run_id)
            raise

        # 2. Attempt resume
        history: list[dict] = []
        resumed_from = 0
        if self.checkpoint_store:
            cp = self.checkpoint_store.load(run_id)
            if cp:
                history = cp.history
                resumed_from = cp.step
                logger.info(
                    "[harness] run_id=%s resuming from step %d", run_id, resumed_from
                )

        # 3. Execute with retry + circuit breaker
        step = resumed_from

        async def _call() -> tuple[str, list[dict], dict]:
            return await agent_fn(task, history)

        output, new_history, usage = await async_retry(
            _call,
            policy=self.policy,
            circuit=self.circuit,
            label=f"agent/{run_id}",
        )
        step += 1

        # 4. Charge budget
        self.budget.charge_input(usage.get("input_tokens", 0))
        self.budget.charge_output(usage.get("output_tokens", 0))
        self.budget.charge_tool_call()  # counts the overall invocation

        # 5. Post-check output
        try:
            self.guardrails.post_check(output)
        except GuardrailViolation:
            logger.warning("[harness] run_id=%s blocked by post-check", run_id)
            raise

        # 6. Clean up checkpoint on success
        if self.checkpoint_store:
            self.checkpoint_store.delete(run_id)

        elapsed = time.monotonic() - started_at
        logger.info(
            "[harness] run_id=%s done steps=%d elapsed=%.2fs",
            run_id, step, elapsed,
        )

        return RunResult(
            run_id=run_id,
            output=output,
            steps_taken=step,
            elapsed_seconds=elapsed,
            budget_summary=self.budget.summary(),
            resumed_from_step=resumed_from,
        )

    # ------------------------------------------------------------------
    # Step-level helpers (for multi-step agents that checkpoint each step)
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
        """
        Charge incremental usage mid-run.  Call after each LLM response.
        Raises BudgetExceededError if any limit is crossed.
        """
        if input_tokens:
            self.budget.charge_input(input_tokens)
        if output_tokens:
            self.budget.charge_output(output_tokens)
        if tool_call:
            self.budget.charge_tool_call()
