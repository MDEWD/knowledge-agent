from __future__ import annotations

import json

import pytest

from agents.deep_research.budget import (
    ModelPrice,
    ResearchBudget,
    ResearchBudgetExceeded,
)
from agents.deep_research.evidence import Evidence
from agents.deep_research.state import (
    Critique,
    CritiqueCategory,
    CritiqueSeverity,
    CritiqueStatus,
    EvaluationSnapshot,
    ResearchNote,
    ResearchPhase,
    ResearchState,
    ResearchStatus,
)
from agents.deep_research.stop_policy import StopPolicy, StopReason


def _evaluation(iteration: int, score: float, evidence_count: int, coverage: float = 0.5):
    return EvaluationSnapshot(
        iteration=iteration,
        comprehensiveness_score=score,
        accuracy_score=score,
        coherence_score=score,
        evidence_coverage=coverage,
        evidence_count=evidence_count,
    )


def test_research_state_checkpoint_round_trip_is_json_serializable():
    evidence = Evidence.create(
        url="https://example.com/report?utm_source=test",
        title="Primary report",
        query="industry report",
        snippet="source excerpt",
        authority_score=0.9,
    )
    state = ResearchState(
        run_id="run-1",
        phase=ResearchPhase.RESEARCHING,
        status=ResearchStatus.RUNNING,
        iteration=3,
        brief="brief",
        draft="# report",
        evidence=[evidence],
        notes=[ResearchNote(topic="market", content="note", evidence_ids=[evidence.source_id])],
        evaluations=[_evaluation(3, 7.5, 1, 0.8)],
        supervisor_messages=[{"role": "assistant", "content": None, "tool_calls": []}],
        query_history=["industry report"],
    )
    state.usage.records.append(
        ResearchBudget().charge_llm(
            role="supervisor", model="deepseek-v4-flash", input_tokens=10, output_tokens=2
        )
    )

    payload = state.to_checkpoint_json()
    json.loads(payload)  # no custom JSON encoder is required
    restored = ResearchState.from_checkpoint_json(payload)

    assert restored.run_id == "run-1"
    assert restored.phase is ResearchPhase.RESEARCHING
    assert restored.evidence[0].source_id == evidence.source_id
    assert restored.notes[0].evidence_ids == [evidence.source_id]
    assert restored.usage.input_tokens == 10
    assert restored.supervisor_messages[0]["content"] is None


def test_critique_lifecycle_tracks_resolution_and_rejects_double_close():
    state = ResearchState(iteration=4)
    critique = Critique(
        critique_id="crit-1",
        category=CritiqueCategory.FACT,
        severity=CritiqueSeverity.HIGH,
        problem="claim is unsupported",
    )
    state.add_critique(critique)
    assert state.has_open_high_critique

    closed = state.resolve_critique("crit-1", "added two primary sources")
    assert closed.status is CritiqueStatus.RESOLVED
    assert closed.closed_iteration == 4
    assert not state.has_open_high_critique
    with pytest.raises(ValueError, match="already resolved"):
        state.reject_critique("crit-1", "not applicable")


def test_budget_accounts_for_every_role_tool_and_estimated_cost():
    budget = ResearchBudget(
        prices={"deepseek-v4": ModelPrice(input_per_million_usd=1.0, output_per_million_usd=2.0)},
        max_cost_usd=1.0,
        max_tool_calls=5,
    )
    budget.charge_llm(
        role="supervisor",
        model="deepseek-v4-flash",
        input_tokens=100_000,
        output_tokens=10_000,
    )
    budget.charge_llm(
        role="red_team",
        model="deepseek-v4-pro",
        input_tokens=50_000,
        output_tokens=5_000,
    )
    budget.charge_tool("tavily_search", calls=2, cost_usd=0.02)

    summary = budget.summary()
    assert summary["input_tokens"] == 150_000
    assert summary["output_tokens"] == 15_000
    assert summary["tool_calls"] == 2
    assert summary["cost_usd"] == pytest.approx(0.20)
    assert summary["by_role"]["supervisor"]["calls"] == 1
    assert summary["by_role"]["red_team"]["calls"] == 1
    assert summary["by_tool"]["tavily_search"]["calls"] == 2


def test_budget_is_a_hard_limit_and_keeps_crossing_usage_for_observability():
    budget = ResearchBudget(max_input_tokens=100, max_tool_calls=1)
    budget.charge_llm(role="writer", model="test", input_tokens=100, output_tokens=0)
    with pytest.raises(ResearchBudgetExceeded, match="input_tokens 101>100"):
        budget.charge_llm(role="writer", model="test", input_tokens=1, output_tokens=0)
    assert budget.usage.input_tokens == 101

    budget = ResearchBudget(max_tool_calls=1)
    with pytest.raises(ResearchBudgetExceeded, match="tool_calls 2>1"):
        budget.charge_tool("search", calls=2)


def test_stop_policy_max_iteration_and_budget_are_forced():
    policy = StopPolicy(max_iterations=15)
    decision = policy.evaluate(ResearchState(iteration=15))
    assert decision.should_stop and decision.forced
    assert decision.reason is StopReason.MAX_ITERATIONS

    budget = ResearchBudget(max_output_tokens=1)
    with pytest.raises(ResearchBudgetExceeded):
        budget.charge_llm(role="writer", model="x", input_tokens=0, output_tokens=2)
    decision = policy.evaluate(ResearchState(iteration=2), budget)
    assert decision.should_stop and decision.forced
    assert decision.reason is StopReason.BUDGET_EXCEEDED


def test_high_critique_gates_quality_completion_until_resolved():
    policy = StopPolicy()
    state = ResearchState(
        iteration=4,
        evaluations=[_evaluation(4, 9.0, 10, 0.95)],
        critiques=[
            Critique(
                critique_id="high-1",
                category=CritiqueCategory.CITATION,
                severity=CritiqueSeverity.HIGH,
                problem="citation does not support claim",
            )
        ],
    )
    decision = policy.evaluate(state)
    assert not decision.should_stop
    assert decision.reason is StopReason.HIGH_CRITIQUE_OPEN

    state.resolve_critique("high-1", "citation replaced")
    decision = policy.evaluate(state)
    assert decision.should_stop
    assert decision.reason is StopReason.QUALITY_REACHED


def test_stop_policy_detects_score_plateau_and_no_new_evidence():
    policy = StopPolicy(score_plateau_rounds=2, score_min_improvement=0.3)
    plateau = ResearchState(
        iteration=5,
        evaluations=[
            _evaluation(3, 7.0, 4),
            _evaluation(4, 7.2, 5),
            _evaluation(5, 7.3, 6),
        ],
    )
    assert policy.evaluate(plateau).reason is StopReason.SCORE_PLATEAU

    no_evidence = ResearchState(
        iteration=5,
        evaluations=[
            _evaluation(3, 5.0, 4),
            _evaluation(4, 6.0, 4),
            _evaluation(5, 7.0, 4),
        ],
    )
    assert policy.evaluate(no_evidence).reason is StopReason.NO_NEW_EVIDENCE


def test_stop_policy_continues_when_quality_or_coverage_is_insufficient():
    state = ResearchState(iteration=2, evaluations=[_evaluation(2, 8.5, 3, 0.6)])
    decision = StopPolicy().evaluate(state)
    assert not decision.should_stop
    assert decision.reason is StopReason.CONTINUE
