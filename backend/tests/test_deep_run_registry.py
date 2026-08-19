from __future__ import annotations

import asyncio

import pytest

from agents.deep_research.run_registry import DeepRunRegistry


@pytest.mark.asyncio
async def test_research_continues_after_first_sse_subscriber_disconnects():
    registry = DeepRunRegistry()
    continue_run = asyncio.Event()

    async def runner(record):
        await record.publish({"type": "run_started", "run_id": record.run_id})
        await record.publish({"type": "research_brief", "content": "brief"})
        await continue_run.wait()
        await record.publish({"type": "report_replace", "content": "final report"})

    record = registry.start(
        owner_id="user-1",
        run_id="user-1:run-1",
        task="original question",
        session_id="session-1",
        runner=runner,
    )

    first_stream = record.stream(after=0, heartbeat_seconds=0.05)
    first_seq, first_event = await anext(first_stream)
    assert first_seq == 1
    assert first_event["type"] == "run_started"
    await first_stream.aclose()  # browser refresh / SSE disconnect

    continue_run.set()
    await record.runner_task

    replayed = [event async for _, event in record.stream(after=0, heartbeat_seconds=0.05)]
    assert any(event.get("type") == "research_brief" for event in replayed)
    assert any(event.get("type") == "report_replace" for event in replayed)
    assert replayed[-1]["type"] == "done"
    assert record.status == "completed"


@pytest.mark.asyncio
async def test_registry_scopes_active_runs_by_owner():
    registry = DeepRunRegistry()
    release = asyncio.Event()

    async def runner(record):
        await release.wait()

    record = registry.start("user-1", "user-1:run", "question", "session", runner)
    assert [item.run_id for item in registry.active_for("user-1")] == [record.run_id]
    assert registry.active_for("user-2") == []
    assert registry.get_for_owner(record.run_id, "user-2") is None

    release.set()
    await record.runner_task


@pytest.mark.asyncio
async def test_registry_shutdown_cancels_and_awaits_active_runs():
    registry = DeepRunRegistry()
    started = asyncio.Event()

    async def runner(_record):
        started.set()
        await asyncio.Event().wait()

    record = registry.start("user-1", "user-1:run", "question", "session", runner)
    await started.wait()

    await registry.shutdown()

    assert record.runner_task.done()
    assert record.status == "cancelled"
