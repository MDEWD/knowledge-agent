from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.deep_research.evaluator import evaluate_draft_quality
from harness.retry import RetryPolicy


def _response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    '```json\n{"comprehensiveness_score": 8, "accuracy_score": 9, '
    '"coherence_score": 7, "evidence_coverage": 0.8, "reason": "ok"}\n```',
    '评分如下：\n{"comprehensiveness_score": 8, "accuracy_score": 9, '
    '"coherence_score": 7, "evidence_coverage": 0.8, "reason": "ok"}',
])
async def test_evaluator_accepts_wrapped_json(raw):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=_response(raw)),
    )))
    result = await evaluate_draft_quality(
        client,
        "judge",
        research_brief="brief",
        draft_report="draft",
        policy=RetryPolicy(max_attempts=1),
    )
    assert result.average == 8
    assert result.reason == "ok"


@pytest.mark.asyncio
async def test_evaluator_retries_empty_or_truncated_json():
    valid = (
        '{"comprehensiveness_score": 9, "accuracy_score": 8, '
        '"coherence_score": 7, "evidence_coverage": 0.75, "reason": "recovered"}'
    )
    create = AsyncMock(side_effect=[_response('{"comprehensiveness_score": 9'), _response(valid)])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = await evaluate_draft_quality(
        client,
        "judge",
        research_brief="brief",
        draft_report="draft",
        policy=RetryPolicy(max_attempts=2, base_delay=0),
    )
    assert result.average == 8
    assert result.reason == "recovered"
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_evaluator_falls_back_to_reasoning_content():
    raw = (
        '{"comprehensiveness_score": 7, "accuracy_score": 8, '
        '"coherence_score": 9, "evidence_coverage": 0.7, "reason": "reasoning"}'
    )
    response = _response("")
    response.choices[0].message.reasoning_content = raw
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=response),
    )))
    result = await evaluate_draft_quality(
        client,
        "judge",
        research_brief="brief",
        draft_report="draft",
        policy=RetryPolicy(max_attempts=1),
    )
    assert result.average == 8
    assert result.reason == "reasoning"


@pytest.mark.asyncio
async def test_evaluator_checks_reasoning_candidate_and_allows_final_json_budget():
    raw = (
        '{"comprehensiveness_score": 8, "accuracy_score": 8, '
        '"coherence_score": 8, "evidence_coverage": 0.8, "reason": "valid"}'
    )
    response = _response("先分析研究简报，但这里没有最终 JSON")
    response.choices[0].message.reasoning_content = raw
    create = AsyncMock(return_value=response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = await evaluate_draft_quality(
        client,
        "judge",
        research_brief="brief",
        draft_report="draft",
        policy=RetryPolicy(max_attempts=1),
    )
    assert result.average == 8
    assert create.await_args.kwargs["max_tokens"] >= 2048
