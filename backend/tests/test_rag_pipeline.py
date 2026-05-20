"""
Unit tests for the RAG enhancement pipeline.

Covers
------
- rerank()      : boundary conditions, error fallback, top_k enforcement
- rewrite_query(): non-empty output, API-failure fallback
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from processors.rag_enhancer import rerank


# ---------------------------------------------------------------------------
# rerank()
# ---------------------------------------------------------------------------

def _chunks(n: int) -> list[dict]:
    return [{"content": f"chunk {i}", "metadata": {"title": f"doc {i}"}} for i in range(n)]


def test_rerank_empty_input_returns_empty():
    """rerank() on an empty list must return [] without touching the model."""
    with patch("processors.rag_enhancer.get_reranker") as mock_get:
        result = rerank("some query", [], top_k=6)
    assert result == []
    mock_get.assert_not_called()


def test_rerank_enforces_top_k():
    """rerank() must return at most top_k items."""
    chunks = _chunks(20)
    with patch("processors.rag_enhancer.get_reranker") as mock_get:
        reranker = MagicMock()
        reranker.predict.return_value = list(range(20, 0, -1))
        mock_get.return_value = reranker

        result = rerank("query", chunks, top_k=6)

    assert len(result) <= 6


def test_rerank_sorts_by_score_descending():
    """Highest-scored chunk must come first."""
    chunks = _chunks(5)
    scores = [0.1, 0.9, 0.3, 0.7, 0.5]  # chunk 1 is best

    with patch("processors.rag_enhancer.get_reranker") as mock_get:
        reranker = MagicMock()
        reranker.predict.return_value = scores
        mock_get.return_value = reranker

        result = rerank("query", chunks, top_k=3)

    assert result[0]["content"] == "chunk 1"


def test_rerank_fewer_than_top_k():
    """If fewer chunks than top_k exist, all are returned."""
    chunks = _chunks(3)
    with patch("processors.rag_enhancer.get_reranker") as mock_get:
        reranker = MagicMock()
        reranker.predict.return_value = [0.8, 0.5, 0.3]
        mock_get.return_value = reranker

        result = rerank("query", chunks, top_k=10)

    assert len(result) == 3


def test_rerank_fallback_on_model_error():
    """If the cross-encoder raises, rerank falls back to first top_k in original order."""
    chunks = _chunks(10)
    with patch("processors.rag_enhancer.get_reranker") as mock_get:
        mock_get.side_effect = RuntimeError("model not available")

        result = rerank("query", chunks, top_k=4)

    assert len(result) == 4
    assert result[0]["content"] == "chunk 0"


def test_rerank_fallback_on_predict_error():
    """If predict() raises, rerank still falls back gracefully."""
    chunks = _chunks(8)
    with patch("processors.rag_enhancer.get_reranker") as mock_get:
        reranker = MagicMock()
        reranker.predict.side_effect = RuntimeError("predict failed")
        mock_get.return_value = reranker

        result = rerank("query", chunks, top_k=3)

    assert len(result) == 3


# ---------------------------------------------------------------------------
# rewrite_query()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rewrite_query_returns_nonempty():
    """rewrite_query() returns the LLM-rewritten string when the call succeeds."""
    from processors.rag_enhancer import rewrite_query

    choice = MagicMock()
    choice.message.content = "投资理财 资产配置 风险管理"
    resp = MagicMock()
    resp.choices = [choice]

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)

    result = await rewrite_query("how do I invest money", client, "test-model")

    assert result
    assert len(result) > 0
    assert result == "投资理财 资产配置 风险管理"


@pytest.mark.asyncio
async def test_rewrite_query_fallback_on_error():
    """If the LLM call fails, the original query is returned unchanged."""
    from processors.rag_enhancer import rewrite_query

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("timeout"))

    original = "how to manage personal finance"
    result = await rewrite_query(original, client, "test-model")

    assert result == original


@pytest.mark.asyncio
async def test_rewrite_query_fallback_on_empty_response():
    """If the LLM returns an empty string, the original query is returned."""
    from processors.rag_enhancer import rewrite_query

    choice = MagicMock()
    choice.message.content = ""
    resp = MagicMock()
    resp.choices = [choice]

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)

    original = "tell me about investing"
    result = await rewrite_query(original, client, "test-model")

    assert result == original
