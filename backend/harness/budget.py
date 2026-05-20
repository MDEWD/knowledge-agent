"""
Token budget enforcement for agent runs.

Design:
  - TokenBudget is stateful and tracks consumption across the lifetime of one run.
  - Raise BudgetExceededError the moment any single limit is crossed.
  - Callers should instantiate one TokenBudget per AgentHarness.run() invocation.

Usage:
    budget = TokenBudget(max_input=50_000, max_output=10_000)

    budget.charge_input(prompt_tokens)
    budget.charge_output(completion_tokens)
    budget.charge_tool_call()          # increments tool-call counter
    budget.summary()                   # → dict for observability
"""
from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceededError(RuntimeError):
    """Raised when a token or call budget is exceeded."""


@dataclass
class TokenBudget:
    """
    Tracks and enforces per-run token / call limits.

    All limits are optional (None = no limit).
    """
    max_input_tokens: int | None = None     # cumulative input tokens
    max_output_tokens: int | None = None    # cumulative output tokens
    max_tool_calls: int | None = None       # number of tool invocations

    _input_used: int = field(default=0, init=False, repr=False)
    _output_used: int = field(default=0, init=False, repr=False)
    _tool_calls: int = field(default=0, init=False, repr=False)

    # ------------------------------------------------------------------
    # Charging
    # ------------------------------------------------------------------

    def charge_input(self, tokens: int) -> None:
        """Record input tokens; raise if the cumulative limit is exceeded."""
        self._input_used += tokens
        if self.max_input_tokens is not None and self._input_used > self.max_input_tokens:
            raise BudgetExceededError(
                f"Input token budget exceeded: used {self._input_used}, "
                f"limit {self.max_input_tokens}"
            )

    def charge_output(self, tokens: int) -> None:
        """Record output tokens; raise if the cumulative limit is exceeded."""
        self._output_used += tokens
        if self.max_output_tokens is not None and self._output_used > self.max_output_tokens:
            raise BudgetExceededError(
                f"Output token budget exceeded: used {self._output_used}, "
                f"limit {self.max_output_tokens}"
            )

    def charge_tool_call(self) -> None:
        """Increment tool-call counter; raise if the limit is exceeded."""
        self._tool_calls += 1
        if self.max_tool_calls is not None and self._tool_calls > self.max_tool_calls:
            raise BudgetExceededError(
                f"Tool-call budget exceeded: made {self._tool_calls}, "
                f"limit {self.max_tool_calls}"
            )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def input_used(self) -> int:
        return self._input_used

    @property
    def output_used(self) -> int:
        return self._output_used

    @property
    def tool_calls(self) -> int:
        return self._tool_calls

    def summary(self) -> dict:
        """Return a dict suitable for logging / LangFuse metadata."""
        return {
            "input_tokens": self._input_used,
            "output_tokens": self._output_used,
            "tool_calls": self._tool_calls,
            "limits": {
                "max_input_tokens": self.max_input_tokens,
                "max_output_tokens": self.max_output_tokens,
                "max_tool_calls": self.max_tool_calls,
            },
        }
