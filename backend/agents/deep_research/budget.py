"""Usage accounting and hard budgets for a DeepResearch run.

The ledger is deliberately independent from any LLM SDK.  Callers charge every
model response and tool invocation at the boundary where it completes.  This
makes accounting work for Supervisor, Researcher, Red Team and Writer alike.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ResearchBudgetExceeded(RuntimeError):
    """Raised immediately after a configured run limit is crossed."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("Research budget exceeded: " + "; ".join(reasons))


class ModelPrice(BaseModel):
    """USD price per one million tokens."""

    input_per_million_usd: float = Field(default=0.0, ge=0)
    output_per_million_usd: float = Field(default=0.0, ge=0)


class UsageRecord(BaseModel):
    kind: str
    name: str
    role: str | None = None
    model: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UsageLedger(BaseModel):
    """JSON-serializable, per-call usage ledger."""

    records: list[UsageRecord] = Field(default_factory=list)

    @property
    def input_tokens(self) -> int:
        return sum(item.input_tokens for item in self.records)

    @property
    def output_tokens(self) -> int:
        return sum(item.output_tokens for item in self.records)

    @property
    def tool_calls(self) -> int:
        return sum(item.tool_calls for item in self.records)

    @property
    def cost_usd(self) -> float:
        return sum(item.cost_usd for item in self.records)

    def by_role(self) -> dict[str, dict[str, float | int]]:
        totals: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "calls": 0, "cost_usd": 0.0}
        )
        for item in self.records:
            if item.kind != "llm":
                continue
            role = item.role or "unknown"
            totals[role]["input_tokens"] += item.input_tokens
            totals[role]["output_tokens"] += item.output_tokens
            totals[role]["calls"] += 1
            totals[role]["cost_usd"] += item.cost_usd
        return dict(totals)

    def by_tool(self) -> dict[str, dict[str, float | int]]:
        totals: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {"calls": 0, "cost_usd": 0.0}
        )
        for item in self.records:
            if item.kind != "tool":
                continue
            totals[item.name]["calls"] += item.tool_calls
            totals[item.name]["cost_usd"] += item.cost_usd
        return dict(totals)

    def summary(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_calls": self.tool_calls,
            "cost_usd": round(self.cost_usd, 8),
            "by_role": self.by_role(),
            "by_tool": self.by_tool(),
        }


class ResearchBudget(BaseModel):
    """Accumulates real usage and enforces token/call/cost limits.

    Pricing is configuration, not a hard-coded claim about a provider.  Unknown
    models use ``default_price`` so private gateways and new model aliases remain
    accountable.
    """

    max_input_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)
    max_tool_calls: int | None = Field(default=None, ge=0)
    max_cost_usd: float | None = Field(default=None, ge=0)
    prices: dict[str, ModelPrice] = Field(default_factory=dict)
    default_price: ModelPrice = Field(default_factory=ModelPrice)
    usage: UsageLedger = Field(default_factory=UsageLedger)

    @model_validator(mode="after")
    def _validate_restored_budget(self) -> "ResearchBudget":
        # Restoring an over-limit checkpoint is allowed: StopPolicy can turn it
        # into a controlled terminal report instead of making restore impossible.
        return self

    def _price_for(self, model: str) -> ModelPrice:
        if model in self.prices:
            return self.prices[model]
        # Allow a configured provider model to match versioned aliases.
        matches = [(name, price) for name, price in self.prices.items() if model.startswith(name)]
        return max(matches, key=lambda item: len(item[0]))[1] if matches else self.default_price

    def charge_llm(
        self,
        *,
        role: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> UsageRecord:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token usage cannot be negative")
        price = self._price_for(model)
        cost = (
            input_tokens * price.input_per_million_usd
            + output_tokens * price.output_per_million_usd
        ) / 1_000_000
        record = UsageRecord(
            kind="llm",
            name=model,
            role=role,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        self.usage.records.append(record)
        self.raise_if_exceeded()
        return record

    def charge_tool(self, tool_name: str, *, calls: int = 1, cost_usd: float = 0.0) -> UsageRecord:
        if calls < 0 or cost_usd < 0:
            raise ValueError("tool usage cannot be negative")
        record = UsageRecord(
            kind="tool",
            name=tool_name,
            tool_calls=calls,
            cost_usd=cost_usd,
        )
        self.usage.records.append(record)
        self.raise_if_exceeded()
        return record

    def exceeded_reasons(self) -> list[str]:
        reasons: list[str] = []
        if self.max_input_tokens is not None and self.usage.input_tokens > self.max_input_tokens:
            reasons.append(f"input_tokens {self.usage.input_tokens}>{self.max_input_tokens}")
        if self.max_output_tokens is not None and self.usage.output_tokens > self.max_output_tokens:
            reasons.append(f"output_tokens {self.usage.output_tokens}>{self.max_output_tokens}")
        if self.max_tool_calls is not None and self.usage.tool_calls > self.max_tool_calls:
            reasons.append(f"tool_calls {self.usage.tool_calls}>{self.max_tool_calls}")
        if self.max_cost_usd is not None and self.usage.cost_usd > self.max_cost_usd:
            reasons.append(f"cost_usd {self.usage.cost_usd:.8f}>{self.max_cost_usd:.8f}")
        return reasons

    def raise_if_exceeded(self) -> None:
        reasons = self.exceeded_reasons()
        if reasons:
            raise ResearchBudgetExceeded(reasons)

    def summary(self) -> dict[str, Any]:
        return {
            **self.usage.summary(),
            "limits": {
                "max_input_tokens": self.max_input_tokens,
                "max_output_tokens": self.max_output_tokens,
                "max_tool_calls": self.max_tool_calls,
                "max_cost_usd": self.max_cost_usd,
            },
            "exceeded": self.exceeded_reasons(),
        }
