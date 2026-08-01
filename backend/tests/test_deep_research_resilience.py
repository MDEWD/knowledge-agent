from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError

from agents.deep_research.sub_researcher import SubResearcher
from agents.deep_research.orchestrator import DeepResearchOrchestrator
from agents.deep_research.model_runtime import apply_role_options
from harness.retry import CircuitBreaker, RetryPolicy, async_retry


def _llm_response(content: str = "ok"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )


def test_only_red_team_keeps_thinking_enabled():
    red = apply_role_options({"model": "deepseek-v4-pro"}, "red_team")
    writer = apply_role_options({"model": "deepseek-v4-pro"}, "final_writer")
    assert red["extra_body"] == {"thinking": {"type": "enabled"}}
    assert red["reasoning_effort"] == "high"
    assert writer["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in writer


@pytest.mark.asyncio
async def test_orchestrator_disables_default_thinking_for_supervisor():
    create = AsyncMock(return_value=_llm_response())
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    orchestrator = DeepResearchOrchestrator(
        client,
        "deepseek-v4-flash",
        policy=RetryPolicy(max_attempts=1),
    )
    await orchestrator._llm(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "plan"}],
        _role="supervisor",
    )
    assert create.await_args.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


@pytest.mark.asyncio
async def test_subresearcher_disables_default_thinking():
    create = AsyncMock(return_value=_llm_response())
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    researcher = SubResearcher(
        client,
        "deepseek-v4-flash",
        policy=RetryPolicy(max_attempts=1),
    )
    await researcher._llm(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "research"}],
        _role="researcher_main",
    )
    assert create.await_args.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_openai_connection_error_is_retryable():
    error = APIConnectionError(request=httpx.Request("POST", "https://model.invalid"))
    assert RetryPolicy().is_retryable(error)


@pytest.mark.asyncio
async def test_openai_connection_error_is_actually_retried():
    attempts = 0

    async def flaky():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise APIConnectionError(request=httpx.Request("POST", "https://model.invalid"))
        return "ok"

    result = await async_retry(
        flaky,
        policy=RetryPolicy(max_attempts=3, base_delay=0, jitter=0),
        label="test-connection",
    )
    assert result == "ok"
    assert attempts == 3


@pytest.mark.asyncio
async def test_circuit_counts_one_exhausted_operation_not_each_attempt():
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60)

    async def unavailable():
        raise APIConnectionError(request=httpx.Request("POST", "https://model.invalid"))

    with pytest.raises(APIConnectionError):
        await async_retry(
            unavailable,
            policy=RetryPolicy(max_attempts=3, base_delay=0, jitter=0),
            circuit=breaker,
            label="test-circuit",
        )
    assert breaker.state == "closed"
    assert breaker._failures == 1


@pytest.mark.asyncio
async def test_tavily_uses_provider_excerpt_without_redundant_llm_summary(monkeypatch):
    from agents.deep_research import search_router

    captured = {}

    class FakeTavilyClient:
        def __init__(self, **_kwargs):
            pass

        def search(self, **kwargs):
            captured.update(kwargs)
            return {"results": [{
                "title": "Official release",
                "url": "https://example.com/release",
                "content": "bounded provider excerpt",
                "raw_content": "raw-page-" * 1000,
            }]}

    monkeypatch.setattr(search_router._config, "TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(search_router._config, "TAVILY_LLM_SUMMARIZE", False, raising=False)
    monkeypatch.setitem(sys.modules, "tavily", SimpleNamespace(TavilyClient=FakeTavilyClient))
    summarize = AsyncMock(return_value="should not be called")

    result = await search_router._tavily_search_impl("topic", llm_call=summarize)
    assert captured["include_raw_content"] is False
    assert summarize.await_count == 0
    assert "bounded provider excerpt" in result
    assert "raw-page" not in result


@pytest.mark.asyncio
async def test_tavily_content_risk_does_not_reinsert_raw_text(monkeypatch):
    from agents.deep_research import search_router

    marker = "RISK_MARKER_DO_NOT_FORWARD"

    class FakeTavilyClient:
        def __init__(self, **_kwargs):
            pass

        def search(self, **_kwargs):
            return {"results": [{
                "title": "Filtered source",
                "url": "https://example.com/filtered",
                "content": marker * 100,
                "raw_content": marker * 400,
            }]}

    monkeypatch.setattr(search_router._config, "TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(search_router._config, "TAVILY_LLM_SUMMARIZE", True)
    monkeypatch.setitem(sys.modules, "tavily", SimpleNamespace(TavilyClient=FakeTavilyClient))

    async def rejected(_prompt):
        raise RuntimeError("Content Exists Risk")

    events = []

    async def collect(event):
        events.append(event)

    result = await search_router._tavily_search_impl(
        "topic", llm_call=rejected, event_sink=collect,
    )
    assert marker not in result
    assert "内容安全" in result
    assert marker not in events[-1]["evidence"]["snippet"]


def test_compression_transcript_is_bounded():
    messages = [
        {"role": "tool", "content": f"SOURCE-{index}:" + "x" * 20_000}
        for index in range(10)
    ]
    transcript = SubResearcher._format_transcript(messages)
    assert len(transcript) <= 60_000
    assert "SOURCE-9" in transcript


@pytest.mark.asyncio
async def test_compression_failure_falls_back_to_evidence():
    researcher = object.__new__(SubResearcher)
    researcher.compressor_model = "compressor"
    researcher._llm = AsyncMock(side_effect=APIConnectionError(
        request=httpx.Request("POST", "https://model.invalid"),
    ))
    messages = [{"role": "tool", "content": "SOURCE-A usable evidence"}]
    result = await researcher._compress("topic", messages)
    assert "SOURCE-A usable evidence" in result
    assert "压缩模型暂时不可用" in result
