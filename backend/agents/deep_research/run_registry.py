"""Process-local DeepResearch jobs whose lifecycle is independent from SSE clients."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncGenerator, Awaitable, Callable

Runner = Callable[["DeepRunRecord"], Awaitable[None]]


@dataclass
class DeepRunRecord:
    owner_id: str
    run_id: str
    task: str
    session_id: str
    max_events: int = 10_000
    status: str = "running"
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    runner_task: asyncio.Task | None = None
    _events: list[tuple[int, dict]] = field(default_factory=list)
    _next_seq: int = 1
    _condition: asyncio.Condition = field(default_factory=asyncio.Condition)

    @property
    def last_seq(self) -> int:
        return self._next_seq - 1

    async def publish(self, event: dict) -> int:
        async with self._condition:
            seq = self._next_seq
            self._next_seq += 1
            self._events.append((seq, dict(event)))
            if len(self._events) > self.max_events:
                del self._events[: len(self._events) - self.max_events]
            self._condition.notify_all()
        return seq

    async def mark_terminal(self, status: str) -> None:
        async with self._condition:
            self.status = status
            self._condition.notify_all()

    async def stream(
        self,
        *,
        after: int = 0,
        heartbeat_seconds: float = 15.0,
    ) -> AsyncGenerator[tuple[int, dict], None]:
        """Replay buffered events and then wait for new events until terminal."""
        cursor = max(0, int(after))
        while True:
            batch: list[tuple[int, dict]] = []
            terminal = False
            timed_out = False
            async with self._condition:
                batch = [(seq, event) for seq, event in self._events if seq > cursor]
                terminal = self.status != "running"
                if not batch and not terminal:
                    try:
                        await asyncio.wait_for(self._condition.wait(), timeout=heartbeat_seconds)
                    except TimeoutError:
                        timed_out = True
                    continue_after_wait = not timed_out
                else:
                    continue_after_wait = False

            if continue_after_wait:
                continue
            if batch:
                for seq, event in batch:
                    cursor = max(cursor, seq)
                    yield seq, event
                continue
            if terminal:
                return
            if timed_out:
                yield cursor, {"type": "ping"}


class DeepRunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, DeepRunRecord] = {}

    def start(
        self,
        owner_id: str,
        run_id: str,
        task: str,
        session_id: str,
        runner: Runner,
    ) -> DeepRunRecord:
        existing = self._runs.get(run_id)
        if existing and existing.status == "running":
            return existing
        record = DeepRunRecord(owner_id, run_id, task, session_id)
        self._runs[run_id] = record
        record.runner_task = asyncio.create_task(self._run(record, runner))
        return record

    async def _run(self, record: DeepRunRecord, runner: Runner) -> None:
        try:
            await runner(record)
            status = "cancelled" if record.cancel_event.is_set() else "completed"
        except asyncio.CancelledError:
            record.cancel_event.set()
            status = "cancelled"
            raise
        except Exception as exc:
            await record.publish({"type": "error", "message": str(exc)})
            status = "failed"
        finally:
            if not any(event.get("type") == "done" for _, event in record._events):
                await record.publish({"type": "done"})
            await record.mark_terminal(status)

    def get_for_owner(self, run_id: str, owner_id: str) -> DeepRunRecord | None:
        record = self._runs.get(run_id)
        return record if record and record.owner_id == owner_id else None

    def active_for(self, owner_id: str) -> list[DeepRunRecord]:
        records = [
            record for record in self._runs.values()
            if record.owner_id == owner_id and record.status == "running"
        ]
        return sorted(records, key=lambda item: item.started_at, reverse=True)

    async def shutdown(self) -> None:
        """Cancel and await process-local jobs before the event loop closes."""
        tasks = [
            record.runner_task
            for record in self._runs.values()
            if record.runner_task is not None and not record.runner_task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
