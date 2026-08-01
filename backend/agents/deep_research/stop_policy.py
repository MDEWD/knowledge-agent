"""Adaptive completion policy for DeepResearch."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agents.deep_research.budget import ResearchBudget
from agents.deep_research.state import ResearchState, ResearchStatus


class StopReason(str, Enum):
    CONTINUE = "continue"
    MAX_ITERATIONS = "max_iterations"
    BUDGET_EXCEEDED = "budget_exceeded"
    HIGH_CRITIQUE_OPEN = "high_critique_open"
    QUALITY_REACHED = "quality_reached"
    SCORE_PLATEAU = "score_plateau"
    NO_NEW_EVIDENCE = "no_new_evidence"


@dataclass(frozen=True, slots=True)
class StopDecision:
    should_stop: bool
    reason: StopReason
    detail: str
    forced: bool = False


@dataclass(frozen=True, slots=True)
class StopPolicy:
    """Stops on quality or diminishing returns, with 15 as a hard ceiling.

    An unresolved high-severity critique gates all normal completion paths.
    Hard safety limits (iteration and budget) still terminate the run so an
    adversarial critic cannot create an unbounded loop.
    """

    max_iterations: int = 15
    quality_threshold: float = 8.0
    evidence_coverage_threshold: float = 0.90
    score_plateau_rounds: int = 2
    score_min_improvement: float = 0.30
    no_new_evidence_rounds: int = 2

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if self.score_plateau_rounds < 1 or self.no_new_evidence_rounds < 1:
            raise ValueError("adaptive stop windows must be positive")

    def evaluate(self, state: ResearchState, budget: ResearchBudget | None = None) -> StopDecision:
        if state.status is ResearchStatus.BUDGET_EXCEEDED:
            return StopDecision(
                True,
                StopReason.BUDGET_EXCEEDED,
                state.stop_reason or "research budget exceeded",
                forced=True,
            )

        if state.iteration >= self.max_iterations:
            return StopDecision(
                True,
                StopReason.MAX_ITERATIONS,
                f"reached hard iteration limit {self.max_iterations}",
                forced=True,
            )

        budget_reasons = budget.exceeded_reasons() if budget is not None else []
        if budget_reasons:
            return StopDecision(
                True,
                StopReason.BUDGET_EXCEEDED,
                "; ".join(budget_reasons),
                forced=True,
            )

        if state.has_open_high_critique:
            ids = ", ".join(item.critique_id for item in state.open_critiques if item.severity.value == "high")
            return StopDecision(
                False,
                StopReason.HIGH_CRITIQUE_OPEN,
                f"high-severity critiques must be resolved: {ids}",
            )

        latest = state.latest_evaluation
        if (
            latest is not None
            and latest.average >= self.quality_threshold
            and latest.evidence_coverage >= self.evidence_coverage_threshold
        ):
            return StopDecision(
                True,
                StopReason.QUALITY_REACHED,
                f"score={latest.average:.2f}, evidence_coverage={latest.evidence_coverage:.1%}",
            )

        if self._score_has_plateaued(state):
            return StopDecision(
                True,
                StopReason.SCORE_PLATEAU,
                f"score improved by at most {self.score_min_improvement:.2f} for "
                f"{self.score_plateau_rounds} rounds",
            )

        if self._has_no_new_evidence(state):
            return StopDecision(
                True,
                StopReason.NO_NEW_EVIDENCE,
                f"no new unique evidence for {self.no_new_evidence_rounds} rounds",
            )

        return StopDecision(False, StopReason.CONTINUE, "more research is required")

    def _score_has_plateaued(self, state: ResearchState) -> bool:
        required = self.score_plateau_rounds + 1
        if len(state.evaluations) < required:
            return False
        recent = state.evaluations[-required:]
        improvements = [right.average - left.average for left, right in zip(recent, recent[1:])]
        return all(change <= self.score_min_improvement for change in improvements)

    def _has_no_new_evidence(self, state: ResearchState) -> bool:
        required = self.no_new_evidence_rounds + 1
        if len(state.evaluations) < required:
            return False
        counts = [item.evidence_count for item in state.evaluations[-required:]]
        return all(right <= left for left, right in zip(counts, counts[1:]))
