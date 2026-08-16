"""Cancellation-aware await helper shared by all DeepResearch model calls."""
from __future__ import annotations

import asyncio
from typing import Awaitable, TypeVar

T = TypeVar("T")


async def await_with_cancel(
    awaitable: Awaitable[T],
    *,
    timeout_seconds: float,
    cancel_event: asyncio.Event | None,
) -> T:
    if cancel_event is None:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    if cancel_event.is_set():
        if hasattr(awaitable, "close"):
            awaitable.close()  # type: ignore[attr-defined]
        raise asyncio.CancelledError("DeepResearch run cancelled")

    operation = asyncio.ensure_future(awaitable)
    cancellation = asyncio.create_task(cancel_event.wait())
    try:
        done, _ = await asyncio.wait(
            {operation, cancellation},
            timeout=timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancellation in done:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise asyncio.CancelledError("DeepResearch run cancelled")
        if operation not in done:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise asyncio.TimeoutError
        return operation.result()
    finally:
        cancellation.cancel()
        await asyncio.gather(cancellation, return_exceptions=True)
