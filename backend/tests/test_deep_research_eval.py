from agents.deep_research.evidence import Evidence
from agents.deep_research.state import EvaluationSnapshot, ResearchState, ResearchStatus
from evals.deep_research_eval import evaluate_research_run


def test_end_to_end_eval_passes_grounded_diverse_completed_run():
    evidence = [
        Evidence.create(url="https://gov.example/report", title="Gov", query="q"),
        Evidence.create(url="https://academic.example/paper", title="Paper", query="q"),
    ]
    state = ResearchState(
        status=ResearchStatus.COMPLETED,
        final_report=(
            "[Gov](https://gov.example/report) "
            "[Paper](https://academic.example/paper)"
        ),
        evidence=evidence,
        evaluations=[EvaluationSnapshot(
            iteration=3,
            comprehensiveness_score=8,
            accuracy_score=9,
            coherence_score=8,
            evidence_coverage=0.9,
            evidence_count=2,
        )],
    )

    result = evaluate_research_run(state)

    assert result.passed
    assert result.source_diversity == 2


def test_end_to_end_eval_fails_hallucinated_link_and_protocol_error():
    state = ResearchState(
        status=ResearchStatus.COMPLETED,
        final_report="[Fake](https://fake.invalid/report)",
    )

    result = evaluate_research_run(state, [{
        "type": "error",
        "message": "tool_call_id missing tool message",
    }])

    assert not result.passed
    assert "invalid_citations" in result.reasons
    assert "tool_protocol_errors" in result.reasons
