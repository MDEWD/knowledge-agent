"""
Agent task evaluation suite.

Evaluates two frameworks side-by-side:

  Andrew Ng's 4 Agentic Design Patterns
  ──────────────────────────────────────
  1. Reflection    — does the reflection step actually improve answer quality?
  2. Tool Use      — does the system route each query to the correct retrieval path?
  3. Planning      — does multi-agent task decomposition follow a coherent plan?
  4. Multi-agent   — does collaboration produce better output than a single agent?

  VitaBench-inspired Task Success Rate
  ──────────────────────────────────────
  Tasks are bucketed into three complexity levels:
    SIMPLE  — single-tool, unambiguous query (target: >70%)
    MEDIUM  — multi-step or cross-tool query (target: >50%)
    HARD    — cross-domain, requires synthesis or external search (target: >30%)

  Success is graded FULL (1.0) / PARTIAL (0.5) / FAIL (0.0) using RubricScore
  thresholds (not binary LLM-as-Judge).

Results are saved to data/eval_agent_results.json.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import AsyncOpenAI

from config import DATA_PATH, DEEPSEEK_MODEL
from evals.rubric_scorer import RubricScore, score_response, score_conversation

logger = logging.getLogger(__name__)

_RESULTS_PATH = DATA_PATH / "eval_agent_results.json"

# ---------------------------------------------------------------------------
# 1. Tool Use — Intent Classification Accuracy
# ---------------------------------------------------------------------------

# Fixed probe queries whose correct intent is unambiguous regardless of KB content
_INTENT_PROBES: list[dict] = [
    # Temporal — must trigger "temporal" route
    {"query": "最近加了哪些视频？",            "expected": "temporal"},
    {"query": "上周我导入了什么内容？",        "expected": "temporal"},
    {"query": "最新导入的笔记是什么？",        "expected": "temporal"},
    # Entity — must trigger "entity" route
    {"query": "这个视频讲了什么内容？",        "expected": "entity"},
    {"query": "Andrew Ng的课程讲了什么？",     "expected": "entity"},
    # Conceptual — must trigger "conceptual" route
    {"query": "机器学习中的梯度下降是什么原理？", "expected": "conceptual"},
    {"query": "如何提升RAG系统的召回率？",      "expected": "conceptual"},
    {"query": "什么是知识图谱？",              "expected": "conceptual"},
]


async def eval_tool_selection(client: "AsyncOpenAI") -> dict:
    """
    Test intent classification accuracy.
    Maps to Agentic Design Pattern: Tool Use.
    """
    from processors.rag_enhancer import classify_intent

    results = []
    for probe in _INTENT_PROBES:
        predicted = await classify_intent(probe["query"], client, DEEPSEEK_MODEL)
        correct = predicted == probe["expected"]
        results.append({
            "query": probe["query"],
            "expected": probe["expected"],
            "predicted": predicted,
            "correct": correct,
        })

    accuracy = sum(r["correct"] for r in results) / len(results)
    by_intent: dict[str, dict] = {}
    for r in results:
        k = r["expected"]
        by_intent.setdefault(k, {"total": 0, "correct": 0})
        by_intent[k]["total"] += 1
        if r["correct"]:
            by_intent[k]["correct"] += 1

    return {
        "pattern": "tool_use",
        "metric": "intent_classification_accuracy",
        "overall_accuracy": round(accuracy, 3),
        "by_intent": {
            k: round(v["correct"] / v["total"], 3)
            for k, v in by_intent.items()
        },
        "per_probe": results,
    }


# ---------------------------------------------------------------------------
# 2. Reflection — Gain from Self-Critique
# ---------------------------------------------------------------------------

async def eval_reflection_gain(client: "AsyncOpenAI", n_samples: int = 5) -> dict:
    """
    A/B test: compare answer quality with vs without the reflection step.
    Maps to Agentic Design Pattern: Reflection.

    Dynamically samples queries from KB so results are always relevant.
    """
    from storage.vector_store import search

    _QUERY_GEN = """\
根据以下知识库内容，生成一个需要综合理解才能回答的问题（中文，20字以内）。
只返回问题本身，不要其他内容。
内容：{content}"""

    _ANSWER_PROMPT = "根据以下上下文用中文回答问题。\n\n上下文：{context}\n\n问题：{question}"

    _REFLECT_PROMPT = """\
你刚才回答了一个问题，请检查回答是否完整、准确，并给出改进后的版本。
原问题：{question}
原回答：{answer}
上下文：{context}
请直接输出改进后的回答，不要解释。"""

    # Sample chunks from vector store
    try:
        from storage.vector_store import _get_collection
        col = _get_collection()
        docs_data = col.get(include=["documents", "metadatas"])
        docs = docs_data.get("documents") or []
        if not docs:
            return {"pattern": "reflection", "error": "knowledge base is empty"}
        import random
        samples = random.sample(docs, min(n_samples, len(docs)))
    except Exception as e:
        return {"pattern": "reflection", "error": str(e)}

    results = []
    for doc in samples:
        context = doc[:1500]

        # Generate a test question from this chunk
        try:
            q_resp = await client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": _QUERY_GEN.format(content=context)}],
                temperature=0.3, max_tokens=60,
            )
            question = q_resp.choices[0].message.content.strip()
        except Exception:
            continue

        # Answer WITHOUT reflection
        try:
            a_resp = await client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": _ANSWER_PROMPT.format(context=context, question=question)}],
                temperature=0, max_tokens=300,
            )
            answer_base = a_resp.choices[0].message.content.strip()
        except Exception:
            continue

        # Answer WITH reflection (self-critique pass)
        try:
            r_resp = await client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": _REFLECT_PROMPT.format(
                    question=question, answer=answer_base, context=context,
                )}],
                temperature=0, max_tokens=300,
            )
            answer_reflected = r_resp.choices[0].message.content.strip()
        except Exception:
            answer_reflected = answer_base

        # Score both with rubric
        score_base = await score_response(question, answer_base, context, client)
        score_reflected = await score_response(question, answer_reflected, context, client)

        gain = round(score_reflected.normalised - score_base.normalised, 3)
        results.append({
            "question": question,
            "score_base": score_base.to_dict(),
            "score_reflected": score_reflected.to_dict(),
            "gain": gain,
        })

    if not results:
        return {"pattern": "reflection", "error": "no results generated"}

    avg_gain = round(sum(r["gain"] for r in results) / len(results), 3)
    avg_base = round(sum(r["score_base"]["normalised"] for r in results) / len(results), 3)
    avg_reflected = round(sum(r["score_reflected"]["normalised"] for r in results) / len(results), 3)

    return {
        "pattern": "reflection",
        "metric": "normalised_quality_gain",
        "avg_base_score": avg_base,
        "avg_reflected_score": avg_reflected,
        "avg_gain": avg_gain,
        "reflection_helps": avg_gain > 0,
        "per_sample": results,
    }


# ---------------------------------------------------------------------------
# 3. Multi-agent Synergy
# ---------------------------------------------------------------------------

async def eval_multiagent_synergy(client: "AsyncOpenAI") -> dict:
    """
    Compare single-path RAG answer vs multi-agent (Research+Analysis+Writing) output.
    Maps to Agentic Design Pattern: Multi-agent Collaboration.
    """
    from storage.vector_store import search

    _SINGLE_PROMPT = "根据以下上下文，全面回答问题。\n\n上下文：{context}\n\n问题：{question}"

    # Pick a topic that benefits from synthesis across multiple sources
    try:
        from storage.video_db import list_videos
        videos = list_videos()
        if len(videos) < 2:
            return {"pattern": "multi_agent", "skipped": "need at least 2 videos in KB"}
        # Use the most common category as the synthesis topic
        from collections import Counter
        cat_counts = Counter(v.get("category", "其他") for v in videos)
        topic = cat_counts.most_common(1)[0][0]
    except Exception as e:
        return {"pattern": "multi_agent", "error": str(e)}

    question = f"请综合分析知识库中关于「{topic}」的核心观点和关键见解"

    # Single-agent: flat RAG answer
    chunks = search(question, 8)
    context = "\n\n".join(c["content"] for c in chunks[:5])
    try:
        s_resp = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": _SINGLE_PROMPT.format(
                context=context, question=question,
            )}],
            temperature=0, max_tokens=500,
        )
        single_answer = s_resp.choices[0].message.content.strip()
    except Exception as e:
        return {"pattern": "multi_agent", "error": f"single agent failed: {e}"}

    # Multi-agent: orchestrator pipeline
    try:
        from agents.orchestrator import run_agent_pipeline
        multi_chunks: list[str] = []
        async for event in run_agent_pipeline(question, client, DEEPSEEK_MODEL):
            if isinstance(event, dict) and event.get("type") == "final":
                multi_answer = event.get("content", "")
                break
        else:
            multi_answer = ""
        if not multi_answer:
            return {"pattern": "multi_agent", "skipped": "orchestrator returned no final output"}
    except Exception as e:
        return {"pattern": "multi_agent", "skipped": f"orchestrator not available: {e}"}

    score_single = await score_response(question, single_answer, context, client)
    score_multi = await score_response(question, multi_answer, context, client)
    synergy = round(score_multi.normalised - score_single.normalised, 3)

    return {
        "pattern": "multi_agent",
        "topic": topic,
        "question": question,
        "score_single_agent": score_single.to_dict(),
        "score_multi_agent": score_multi.to_dict(),
        "synergy_gain": synergy,
        "multi_agent_wins": synergy > 0,
    }


# ---------------------------------------------------------------------------
# 4. Task Success Rate  (VitaBench-inspired)
# ---------------------------------------------------------------------------

_SUCCESS_JUDGE = """\
你是一个严格的任务完成度评估者。

根据以下标准判断任务完成情况：
FULL    = 任务完全完成，回答准确、完整、切题
PARTIAL = 任务部分完成，回答有价值但存在明显遗漏或错误
FAIL    = 任务未完成，回答无关、空洞或错误

只返回 FULL、PARTIAL 或 FAIL，不要其他内容。

任务：{task}
回答：{answer}
"""

_TASK_LEVELS = ["simple", "medium", "hard"]

_TASK_TEMPLATES = {
    "simple": [
        "知识库里有哪些内容？",
        "最近导入了什么视频？",
        "知识库中有多少个视频？",
    ],
    "medium": [
        "请总结知识库中关于{topic}的主要内容",
        "知识库中哪些内容是相互关联的？",
        "请比较知识库中不同来源对同一主题的观点",
    ],
    "hard": [
        "基于知识库内容，生成一篇关于{topic}的综合分析文章",
        "知识库中存在哪些知识空白，建议研究哪些方向？",
        "请跨多个主题总结知识库中最有价值的洞察",
    ],
}


async def _run_task(task: str, client: "AsyncOpenAI") -> str:
    """Run a task through the RAG pipeline and return the answer."""
    from processors.rag_enhancer import classify_intent, rewrite_query, expand_queries, rerank_with_significance
    from storage.vector_store import search
    from processors.significance import get_significance_map

    intent = await classify_intent(task, client, DEEPSEEK_MODEL)

    if intent == "temporal":
        from storage.video_db import list_videos
        videos = sorted(list_videos(), key=lambda v: v.get("created_at", ""), reverse=True)[:5]
        context = "\n".join(f"- 《{v['title']}》 {v.get('created_at','')[:10]}" for v in videos)
    else:
        rewritten = await rewrite_query(task, client, DEEPSEEK_MODEL)
        chunks = search(rewritten, 10)
        sig_map = get_significance_map()
        top = rerank_with_significance(task, chunks, 5, sig_map)
        context = "\n\n".join(c["content"] for c in top)

    try:
        resp = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "根据知识库内容用中文回答，回答要具体有用。"},
                {"role": "user", "content": f"上下文：\n{context}\n\n任务：{task}"},
            ],
            temperature=0, max_tokens=400,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return ""


async def _judge_success(task: str, answer: str, client: "AsyncOpenAI") -> float:
    """Return 1.0 / 0.5 / 0.0 for FULL / PARTIAL / FAIL."""
    if not answer:
        return 0.0
    try:
        resp = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": _SUCCESS_JUDGE.format(task=task, answer=answer)}],
            temperature=0, max_tokens=10,
        )
        verdict = resp.choices[0].message.content.strip().upper()
        if "FULL" in verdict:
            return 1.0
        if "PARTIAL" in verdict:
            return 0.5
        return 0.0
    except Exception:
        return 0.5


async def eval_task_success(client: "AsyncOpenAI") -> dict:
    """
    Run task suite across three complexity levels.
    VitaBench-inspired: FULL / PARTIAL / FAIL grading.
    """
    from storage.video_db import list_videos
    videos = list_videos()
    topic = videos[0].get("category", "AI") if videos else "AI"

    all_results: list[dict] = []

    for level in _TASK_LEVELS:
        templates = _TASK_TEMPLATES[level]
        for template in templates:
            task = template.format(topic=topic)
            t0 = time.time()
            answer = await _run_task(task, client)
            latency = round((time.time() - t0) * 1000)
            success = await _judge_success(task, answer, client)
            rubric = await score_response(task, answer, "", client)

            all_results.append({
                "level": level,
                "task": task,
                "answer": answer[:300],
                "success": success,
                "rubric": rubric.to_dict(),
                "latency_ms": latency,
            })

    # Aggregate by level
    by_level: dict[str, dict] = {}
    for level in _TASK_LEVELS:
        subset = [r for r in all_results if r["level"] == level]
        if not subset:
            continue
        avg_success = sum(r["success"] for r in subset) / len(subset)
        full_rate = sum(1 for r in subset if r["success"] == 1.0) / len(subset)
        by_level[level] = {
            "avg_success": round(avg_success, 3),
            "full_rate": round(full_rate, 3),
            "n": len(subset),
        }

    overall = sum(r["success"] for r in all_results) / len(all_results) if all_results else 0

    return {
        "pattern": "task_success_rate",
        "overall_success_rate": round(overall, 3),
        "by_level": by_level,
        "targets": {"simple": 0.70, "medium": 0.50, "hard": 0.30},
        "meets_target": {
            level: by_level.get(level, {}).get("avg_success", 0) >= target
            for level, target in {"simple": 0.70, "medium": 0.50, "hard": 0.30}.items()
        },
        "per_task": all_results,
    }


# ---------------------------------------------------------------------------
# 5. Multi-turn Stability
# ---------------------------------------------------------------------------

async def eval_multiturn_stability(client: "AsyncOpenAI", turns: int = 6) -> dict:
    """
    Simulate a multi-turn conversation and measure quality degradation.
    Maps to VitaBench's long-horizon coordination challenge.
    """
    from storage.video_db import list_videos
    videos = list_videos()
    if not videos:
        return {"skipped": "knowledge base is empty"}

    topic = videos[0].get("category", "AI")

    # Build a coherent multi-turn conversation script
    turn_templates = [
        f"知识库中关于{topic}有哪些内容？",
        f"其中最重要的观点是什么？",
        f"这些观点有没有相互矛盾的地方？",
        f"能给我一些具体的例子吗？",
        f"如何把这些知识应用到实际中？",
        f"还有哪些相关主题值得深入研究？",
    ][:turns]

    conversation_turns: list[dict] = []
    history: list[dict] = []

    for question in turn_templates:
        from storage.vector_store import search
        chunks = search(question, 5)
        context = "\n\n".join(c["content"] for c in chunks[:3])

        messages = [
            {"role": "system", "content": "你是一个知识库助手，用中文回答问题。"},
            *history,
            {"role": "user", "content": question},
        ]
        try:
            resp = await client.chat.completions.create(
                model=DEEPSEEK_MODEL, messages=messages,
                temperature=0, max_tokens=300,
            )
            answer = resp.choices[0].message.content.strip()
        except Exception:
            answer = ""

        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        conversation_turns.append({"question": question, "answer": answer, "context": context})

    result = await score_conversation(conversation_turns, client)
    result["pattern"] = "multi_turn_stability"
    return result


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def run_agent_eval(client: "AsyncOpenAI") -> dict:
    """
    Run the full agent evaluation suite and save results.

    Returns a summary dict with all pattern scores.
    """
    logger.info("[agent_eval] starting full evaluation suite")
    started = time.time()

    # Run all evals (tool_selection and reflection can run in parallel;
    # task_success, multiagent, multiturn run sequentially to avoid overloading API)
    tool_result, reflection_result = await asyncio.gather(
        eval_tool_selection(client),
        eval_reflection_gain(client),
    )

    task_result = await eval_task_success(client)
    multiagent_result = await eval_multiagent_synergy(client)
    multiturn_result = await eval_multiturn_stability(client)

    output = {
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": round(time.time() - started, 1),
        "summary": {
            "tool_use_accuracy": tool_result.get("overall_accuracy"),
            "reflection_gain": reflection_result.get("avg_gain"),
            "task_success_rate": task_result.get("overall_success_rate"),
            "multiagent_synergy_gain": multiagent_result.get("synergy_gain"),
            "multiturn_degradation": multiturn_result.get("degradation"),
        },
        "tool_use": tool_result,
        "reflection": reflection_result,
        "task_success": task_result,
        "multi_agent": multiagent_result,
        "multi_turn": multiturn_result,
    }

    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("[agent_eval] done, results → %s", _RESULTS_PATH)
    return output
