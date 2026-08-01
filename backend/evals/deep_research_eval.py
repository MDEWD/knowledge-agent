"""Deterministic end-to-end quality gates for a completed Research Run."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from agents.deep_research.citation_validator import CitationValidator
from agents.deep_research.state import CritiqueStatus, ResearchState, ResearchStatus


@dataclass(frozen=True, slots=True)
class DeepResearchEvalResult:
    passed: bool
    citation_valid: bool
    evidence_coverage: float
    source_diversity: int
    critique_resolution_rate: float
    completed: bool
    protocol_errors: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_research_run(
    state: ResearchState,
    events: list[dict] | None = None,
    *,
    min_evidence_coverage: float = 0.8,
    min_source_diversity: int = 2,
) -> DeepResearchEvalResult:
    """Evaluate outcome, evidence grounding and execution trace without an LLM."""
    trace = events or []
    citation_issues = CitationValidator().validate_report_urls(
        state.final_report,
        state.evidence,
    )
    citation_valid = not any(issue.severity == "error" for issue in citation_issues)
    latest = state.latest_evaluation
    coverage = latest.evidence_coverage if latest else 0.0
    domains = {
        (urlsplit(item.url).hostname or item.source_type or item.source_id).casefold()
        for item in state.evidence
    }
    closed = sum(
        item.status in {CritiqueStatus.RESOLVED, CritiqueStatus.REJECTED}
        for item in state.critiques
    )
    resolution_rate = 1.0 if not state.critiques else closed / len(state.critiques)
    protocol_errors = sum(
        event.get("type") == "error"
        and ("tool_call" in event.get("message", "") or "tool message" in event.get("message", "").lower())
        for event in trace
    )
    completed = state.status is ResearchStatus.COMPLETED

    reasons: list[str] = []
    if not completed:
        reasons.append("run_not_completed")
    if not citation_valid:
        reasons.append("invalid_citations")
    if coverage < min_evidence_coverage:
        reasons.append("insufficient_evidence_coverage")
    if len(domains) < min_source_diversity:
        reasons.append("insufficient_source_diversity")
    if resolution_rate < 1.0:
        reasons.append("open_critiques")
    if protocol_errors:
        reasons.append("tool_protocol_errors")

    return DeepResearchEvalResult(
        passed=not reasons,
        citation_valid=citation_valid,
        evidence_coverage=coverage,
        source_diversity=len(domains),
        critique_resolution_rate=resolution_rate,
        completed=completed,
        protocol_errors=protocol_errors,
        reasons=tuple(reasons),
    )


__all__ = ["DeepResearchEvalResult", "evaluate_research_run"]
