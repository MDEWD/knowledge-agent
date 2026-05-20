"""
RAG quality enhancers:
- Query rewriting: LLM rewrites user question into a retrieval-optimized form
- Cross-encoder reranking: re-scores retrieved chunks for better top-k precision
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import AsyncOpenAI

# Lazy-load cross-encoder to avoid startup cost
_reranker = None
_RERANKER_MODEL = "BAAI/bge-reranker-base"  # multilingual, handles Chinese + English


def get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder(_RERANKER_MODEL)
    return _reranker


async def rewrite_query(query: str, client: "AsyncOpenAI", model: str) -> str:
    """
    Rewrite user query into a retrieval-optimized form.
    Expands synonyms, adds implicit context, removes conversational filler.
    Returns original query if rewriting fails.
    """
    prompt = (
        "你是一个搜索查询优化专家。将以下用户问题改写为更适合向量数据库语义检索的形式。\n"
        "要求：\n"
        "1. 保留核心语义，扩展同义词和相关概念\n"
        "2. 去除情感词、礼貌语，保留信息核心\n"
        "3. 如果问题隐含背景，将其明确化\n"
        "4. 直接返回改写后的查询，不要解释\n\n"
        f"原始问题：{query}"
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200,
        )
        rewritten = resp.choices[0].message.content.strip()
        return rewritten if rewritten else query
    except Exception:
        return query


def rerank(query: str, chunks: list[dict], top_k: int = 6) -> list[dict]:
    """
    Re-score retrieved chunks using a cross-encoder.
    Returns top_k chunks sorted by cross-encoder relevance score.
    """
    if not chunks:
        return chunks
    try:
        reranker = get_reranker()
        pairs = [(query, c["content"]) for c in chunks]
        scores = reranker.predict(pairs)
        ranked = sorted(zip(scores, chunks), key=lambda x: -x[0])
        return [c for _, c in ranked[:top_k]]
    except Exception:
        # Fallback: return original order
        return chunks[:top_k]
