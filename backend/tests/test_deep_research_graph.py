from __future__ import annotations

import asyncio

import pytest

from agents.deep_research.budget import ResearchBudget, ResearchBudgetExceeded
from agents.deep_research.evidence import Evidence
from agents.deep_research.graph_runtime import DeepResearchGraphRuntime
from agents.deep_research.cancellation import await_with_cancel
from agents.deep_research.state import EvaluationSnapshot, ResearchState


class FakeOrchestrator:
    def __init__(self, *, fail_draft: bool = False):
        self.budget = ResearchBudget()
        self.calls: list[str] = []
        self.fail_draft = fail_draft

    async def _write_brief(self, task: str) -> str:
        self.calls.append("brief")
        return f"brief:{task}"

    async def _write_draft(self, brief: str) -> str:
        self.calls.append("draft")
        if self.fail_draft:
            raise RuntimeError("draft crashed")
        return "# draft"

    async def _run_supervisor_loop(self, **kwargs):
        self.calls.append("supervisor")
        state: ResearchState = kwargs["research_state"]
        state.iteration += 1
        state.draft = "# grounded draft"
        state.evidence = [Evidence.create(
            url="https://example.com/source",
            title="Primary source",
            query="query",
        )]
        state.evaluations.append(EvaluationSnapshot(
            iteration=state.iteration,
            comprehensiveness_score=9,
            accuracy_score=9,
            coherence_score=9,
            evidence_coverage=1,
            evidence_count=1,
        ))
        state.supervisor_requested_complete = True
        yield {"type": "iteration", "iter": state.iteration, "max": 15}
        yield {"type": "__supervisor_final__", "state": state}

    async def _final_report_stream(self, brief, notes, draft):
        self.calls.append("final")
        yield "# final\n[Source](https://example.com/source)"


class BudgetExhaustedOrchestrator(FakeOrchestrator):
    async def _run_supervisor_loop(self, **kwargs):
        self.calls.append("supervisor")
        if False:
            yield {}
        raise ResearchBudgetExceeded(["output_tokens 11>10"])


@pytest.mark.asyncio
async def test_langgraph_checkpoint_resumes_completed_run_without_repeating_nodes(
    tmp_path,
    caplog,
):
    checkpoint = tmp_path / "deep-research.sqlite"
    first = FakeOrchestrator()
    runtime = DeepResearchGraphRuntime(first, checkpoint_path=checkpoint)
    first_events = [event async for event in runtime.run_stream("question", run_id="run-1")]

    assert first.calls == ["brief", "draft", "supervisor", "final"]
    assert any(event.get("type") == "citation_validation" for event in first_events)
    assert first_events[-1]["type"] == "done"

    resumed = FakeOrchestrator()
    resumed_runtime = DeepResearchGraphRuntime(resumed, checkpoint_path=checkpoint)
    resumed_events = [
        event async for event in resumed_runtime.run_stream("question", run_id="run-1")
    ]

    assert resumed.calls == []
    assert resumed_events[0] == {
        "type": "run_resumed",
        "run_id": "run-1",
        "phase": "complete",
    }
    assert any(event.get("type") == "text" for event in resumed_events)
    assert not any(
        "Deserializing unregistered type agents.deep_research.state" in
        record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_langgraph_cancel_event_stops_before_first_node(tmp_path):
    cancel = asyncio.Event()
    cancel.set()
    fake = FakeOrchestrator()
    runtime = DeepResearchGraphRuntime(
        fake,
        checkpoint_path=tmp_path / "cancel.sqlite",
        cancel_event=cancel,
    )

    events = [event async for event in runtime.run_stream("question", run_id="cancelled")]

    assert fake.calls == []
    state_event = next(event for event in events if event.get("type") == "research_state")
    assert state_event["status"] == "cancelled"


@pytest.mark.asyncio
async def test_langgraph_resumes_from_failed_node_without_repeating_completed_phase(tmp_path):
    checkpoint = tmp_path / "resume.sqlite"
    failing = FakeOrchestrator(fail_draft=True)
    first_runtime = DeepResearchGraphRuntime(failing, checkpoint_path=checkpoint)

    with pytest.raises(RuntimeError, match="draft crashed"):
        _ = [event async for event in first_runtime.run_stream("question", run_id="resume-1")]
    assert failing.calls == ["brief", "draft"]

    resumed = FakeOrchestrator()
    second_runtime = DeepResearchGraphRuntime(resumed, checkpoint_path=checkpoint)
    events = [event async for event in second_runtime.run_stream("question", run_id="resume-1")]

    assert resumed.calls == ["draft", "supervisor", "final"]
    assert events[0]["type"] == "run_resumed"


@pytest.mark.asyncio
async def test_inflight_model_wait_is_cancelled_immediately():
    cancel = asyncio.Event()

    async def slow():
        await asyncio.sleep(10)

    task = asyncio.create_task(await_with_cancel(
        slow(), timeout_seconds=30, cancel_event=cancel,
    ))
    await asyncio.sleep(0)
    cancel.set()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_budget_exhaustion_returns_checkpointed_draft_without_final_llm(tmp_path):
    fake = BudgetExhaustedOrchestrator()
    runtime = DeepResearchGraphRuntime(fake, checkpoint_path=tmp_path / "budget.sqlite")

    events = [event async for event in runtime.run_stream("question", run_id="budget-1")]

    assert fake.calls == ["brief", "draft", "supervisor"]
    assert any(event.get("type") == "budget_exceeded" for event in events)
    assert any(
        event.get("type") == "report_replace" and event.get("content") == "# draft"
        for event in events
    )
