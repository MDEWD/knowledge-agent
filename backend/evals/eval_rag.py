"""
RAG evaluation suite using LLM-as-Judge.

Metrics:
  - faithfulness:    Does the answer contain only info from the retrieved context?
  - answer_relevancy: Does the answer actually address the question?
  - precision_at_k:  Did retrieval find the ground-truth chunk in top-k results?
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI
from config import DATA_PATH, DEEPSEEK_MODEL

_RESULTS_PATH = DATA_PATH / "eval_results.json"

_FAITHFULNESS_PROMPT = """\
评估以下回答是否完全基于提供的上下文，没有出现上下文中不存在的信息。

评分标准：
1.0 = 回答完全基于上下文
0.5 = 回答大部分基于上下文，有少量推断
0.0 = 回答包含上下文中没有的虚构信息

只返回一个0到1之间的小数，不要解释。

上下文：{context}
问题：{question}
回答：{answer}
"""

_RELEVANCY_PROMPT = """\
评估以下回答是否切题地回答了问题。

评分标准：
1.0 = 完全回答了问题
0.5 = 部分回答了问题
0.0 = 没有回答问题或答非所问

只返回一个0到1之间的小数，不要解释。

问题：{question}
回答：{answer}
"""


async def _llm_score(prompt: str, client: AsyncOpenAI) -> float:
    try:
        resp = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=10,
        )
        return float(resp.choices[0].message.content.strip())
    except Exception:
        return 0.5


def precision_at_k(retrieved_ids: list[str], ground_truth_id: str, k: int = 3) -> float:
    """Fraction of top-k results that contain the ground-truth chunk."""
    top_k = retrieved_ids[:k]
    return 1.0 if ground_truth_id in top_k else 0.0


async def run_eval_suite(
    client: AsyncOpenAI,
    test_cases: list[dict],
) -> dict:
    """Run full evaluation on all test cases. Returns metrics dict."""
    from storage.vector_store import search

    results = []
    for case in test_cases:
        question = case.get("question", "")
        ground_truth = case.get("ground_truth", "")
        context = case.get("context", "")
        gt_chunk_id = case.get("chunk_id", "")

        # Retrieve
        t0 = time.time()
        retrieved = search(question, n_results=6)
        latency_ms = (time.time() - t0) * 1000

        retrieved_ids = [
            __import__("hashlib").md5(
                f"{r['metadata'].get('url','')}_{r['metadata'].get('chunk_index',0)}".encode()
            ).hexdigest()
            for r in retrieved
        ]

        retrieved_context = "\n\n".join(r["content"] for r in retrieved[:3])

        # Generate answer from retrieved context
        try:
            ans_resp = await client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "根据提供的上下文回答问题，用中文。"},
                    {"role": "user", "content": f"上下文：\n{retrieved_context}\n\n问题：{question}"},
                ],
                temperature=0,
                max_tokens=300,
            )
            answer = ans_resp.choices[0].message.content.strip()
        except Exception:
            answer = ""

        # Score
        faithfulness = await _llm_score(
            _FAITHFULNESS_PROMPT.format(context=retrieved_context, question=question, answer=answer),
            client,
        )
        relevancy = await _llm_score(
            _RELEVANCY_PROMPT.format(question=question, answer=answer),
            client,
        )
        p_at_3 = precision_at_k(retrieved_ids, gt_chunk_id, k=3)

        results.append({
            "question": question,
            "ground_truth": ground_truth,
            "answer": answer,
            "faithfulness": round(faithfulness, 3),
            "answer_relevancy": round(relevancy, 3),
            "precision_at_3": p_at_3,
            "retrieval_latency_ms": round(latency_ms, 1),
            "source_title": case.get("source_title", ""),
        })

    if not results:
        return {"metrics": {}, "per_case": [], "timestamp": datetime.now().isoformat()}

    avg_faith = sum(r["faithfulness"] for r in results) / len(results)
    avg_rel = sum(r["answer_relevancy"] for r in results) / len(results)
    avg_p3 = sum(r["precision_at_3"] for r in results) / len(results)
    avg_lat = sum(r["retrieval_latency_ms"] for r in results) / len(results)

    output = {
        "timestamp": datetime.now().isoformat(),
        "case_count": len(results),
        "metrics": {
            "faithfulness": round(avg_faith, 3),
            "answer_relevancy": round(avg_rel, 3),
            "precision_at_3": round(avg_p3, 3),
            "avg_retrieval_latency_ms": round(avg_lat, 1),
        },
        "per_case": results,
    }

    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESULTS_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output
