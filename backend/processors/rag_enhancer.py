"""
RAG quality enhancers:
- rewrite_query:           LLM rewrites user question into retrieval-optimized form
- expand_queries:          generate multiple variants for multi-path retrieval
- classify_intent:         route to best retrieval strategy (temporal/entity/conceptual)
- rerank:                  CrossEncoder reranking
- rerank_with_significance: CrossEncoder + significance score boost
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import AsyncOpenAI

_reranker = None
_RERANKER_MODEL = "BAAI/bge-reranker-base"  # multilingual, handles Chinese + English


def get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder(_RERANKER_MODEL)
    return _reranker


# ── Query rewriting ───────────────────────────────────────────────────────────

async def rewrite_query(query: str, client: "AsyncOpenAI", model: str) -> str:
    """
    Rewrite user query into a retrieval-optimized form.
    Expands synonyms, adds implicit context, removes conversational filler.
    Returns original query if rewriting fails.
    """
    from processors.purpose_manager import get_purpose_context
    purpose_context = get_purpose_context()
    purpose_hint = f"\n知识库定位：{purpose_context.strip()}" if purpose_context else ""

    prompt = (
        "你是一个搜索查询优化专家。将以下用户问题改写为更适合向量数据库语义检索的形式。\n"
        "要求：\n"
        "1. 保留核心语义，扩展同义词和相关概念\n"
        "2. 去除情感词、礼貌语，保留信息核心\n"
        "3. 如果问题隐含背景，将其明确化\n"
        "4. 直接返回改写后的查询，不要解释\n"
        f"{purpose_hint}\n\n"
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


# ── Multi-query expansion ─────────────────────────────────────────────────────

async def expand_queries(query: str, client: "AsyncOpenAI", model: str) -> list[str]:
    """
    Generate up to 3 semantically varied query variants for multi-path retrieval.
    Returns [original] + variants (max 4 total).
    """
    prompt = (
        "生成3个语义相近但表述不同的搜索查询变体，从不同角度检索同一主题。\n"
        "直接输出JSON数组，不要任何解释：\n"
        '["变体1", "变体2", "变体3"]\n\n'
        f"原始查询：{query}"
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
        )
        raw = resp.choices[0].message.content.strip()
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        variants = json.loads(match.group()) if match else []
        return [query] + [v for v in variants if isinstance(v, str) and v.strip() != query][:3]
    except Exception:
        return [query]


# ── Intent classification ─────────────────────────────────────────────────────

_TEMPORAL_KEYWORDS = [
    "最近", "最新", "上周", "昨天", "今天", "这周", "上个月", "近期", "刚加的", "新导入", "最后"
]


async def classify_intent(query: str, client: "AsyncOpenAI", model: str) -> str:
    """
    Classify query intent for routing:
    - "temporal"   : time-based ("最近", "上周", "最新")
    - "entity"     : specific video/note lookup ("XXX讲了什么")
    - "conceptual" : topic/concept search (default)
    """
    if any(kw in query for kw in _TEMPORAL_KEYWORDS):
        return "temporal"

    prompt = (
        "判断以下问题的查询意图，只输出一个单词（entity 或 conceptual）：\n"
        "entity     — 询问某个特定视频或笔记的内容（如「XXX视频讲了什么」）\n"
        "conceptual — 询问某个概念、主题或综合性问题\n\n"
        f"问题：{query}\n意图："
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=10,
        )
        intent = resp.choices[0].message.content.strip().lower()
        return "entity" if "entity" in intent else "conceptual"
    except Exception:
        return "conceptual"


# ── Reranking ─────────────────────────────────────────────────────────────────

def rerank(query: str, chunks: list[dict], top_k: int = 6) -> list[dict]:
    """Re-score chunks using CrossEncoder. Returns top_k sorted by relevance."""
    if not chunks:
        return chunks
    try:
        reranker = get_reranker()
        scores = reranker.predict([(query, c["content"]) for c in chunks])
        return [c for _, c in sorted(zip(scores, chunks), key=lambda x: -x[0])[:top_k]]
    except Exception:
        return chunks[:top_k]


def rerank_with_significance(
    query: str,
    chunks: list[dict],
    top_k: int = 6,
    significance_map: dict[str, float] | None = None,
) -> list[dict]:
    """
    CrossEncoder reranking with optional significance score boost.
    Significance adds up to +20% to the CrossEncoder score as a tiebreaker.
    """
    if not chunks:
        return chunks
    try:
        reranker = get_reranker()
        ce_scores = reranker.predict([(query, c["content"]) for c in chunks])

        if significance_map:
            final_scores = [
                ce * (1.0 + 0.2 * significance_map.get(c["metadata"].get("video_id", ""), 0.0))
                for ce, c in zip(ce_scores, chunks)
            ]
        else:
            final_scores = list(ce_scores)

        return [c for _, c in sorted(zip(final_scores, chunks), key=lambda x: -x[0])[:top_k]]
    except Exception:
        return chunks[:top_k]
