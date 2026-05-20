"""
Unit tests for CompletionEvaluator.

Key edge cases covered
----------------------
1. skip_first_steps  — no LLM call should be made until we pass the skip threshold.
2. max_steps ceiling — always returns should_stop=True at the hard limit.
3. confidence threshold — LLM says stop but confidence < threshold → continue.
4. normal stop      — LLM says stop with sufficient confidence → stop.
5. LLM failure      — falls back to should_stop=False so the agent keeps going.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.completion_evaluator import (
    CompletionEvaluator,
    EvalContext,
    ToolCallSummary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_client(json_content: str):
    """Build a minimal mock AsyncOpenAI client that returns json_content."""
    choice = MagicMock()
    choice.message.content = json_content
    resp = MagicMock()
    resp.choices = [choice]

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    return client


def _ctx(steps: int, max_steps: int = 8, tool_calls: int = 0) -> EvalContext:
    return EvalContext(
        task="summarise my investment videos",
        steps_taken=steps,
        max_steps=max_steps,
        tool_calls=[
            ToolCallSummary(tool="search_knowledge_base", result_preview=f"result {i}")
            for i in range(tool_calls)
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skip_first_step_no_llm_call():
    """Step 1 with skip_first_steps=1 → no LLM call, should_stop=False."""
    client = _mock_client("{}")
    ev = CompletionEvaluator(client, "model", skip_first_steps=1)

    decision = await ev.evaluate(_ctx(steps=1))

    assert decision.should_stop is False
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_skip_threshold_is_inclusive():
    """skip_first_steps=2 means steps 1 and 2 are both skipped."""
    client = _mock_client("{}")
    ev = CompletionEvaluator(client, "model", skip_first_steps=2)

    for step in (1, 2):
        decision = await ev.evaluate(_ctx(steps=step))
        assert decision.should_stop is False

    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_max_steps_forces_stop():
    """At max_steps the evaluator must stop, regardless of LLM output."""
    client = _mock_client('{"should_stop": false, "confidence": 0.0}')
    ev = CompletionEvaluator(client, "model")

    decision = await ev.evaluate(_ctx(steps=8, max_steps=8))

    assert decision.should_stop is True
    assert decision.confidence == 1.0
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_confidence_below_threshold_overrides_stop():
    """
    LLM says stop but confidence 0.5 < threshold 0.7
    → should_stop overridden to False.
    """
    client = _mock_client(
        '{"should_stop": true, "confidence": 0.5, "reason": "looks done", "missing": null}'
    )
    ev = CompletionEvaluator(client, "model", confidence_threshold=0.7, skip_first_steps=1)

    decision = await ev.evaluate(_ctx(steps=3, tool_calls=2))

    assert decision.should_stop is False


@pytest.mark.asyncio
async def test_high_confidence_stop():
    """LLM says stop with confidence ≥ threshold → should_stop=True."""
    client = _mock_client(
        '{"should_stop": true, "confidence": 0.9, "reason": "enough info", "missing": null}'
    )
    ev = CompletionEvaluator(client, "model", confidence_threshold=0.7, skip_first_steps=1)

    decision = await ev.evaluate(_ctx(steps=3, tool_calls=2))

    assert decision.should_stop is True
    assert decision.confidence == pytest.approx(0.9)
    assert decision.reason == "enough info"
    assert decision.missing is None


@pytest.mark.asyncio
async def test_llm_failure_defaults_to_continue():
    """If the LLM call raises an exception, default to should_stop=False."""
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API unavailable"))
    ev = CompletionEvaluator(client, "model", skip_first_steps=1)

    decision = await ev.evaluate(_ctx(steps=3))

    assert decision.should_stop is False
    assert decision.confidence == 0.0


@pytest.mark.asyncio
async def test_llm_returns_continue():
    """LLM says should_stop=False → continue normally."""
    client = _mock_client(
        '{"should_stop": false, "confidence": 0.6, "reason": "need more data", "missing": "video list"}'
    )
    ev = CompletionEvaluator(client, "model", skip_first_steps=1)

    decision = await ev.evaluate(_ctx(steps=3, tool_calls=1))

    assert decision.should_stop is False
    assert decision.missing == "video list"
