"""
Rubric-based 1-5 scorer — replaces binary LLM-as-Judge.

Inspired by VitaBench's sliding window evaluator:
  - Partial credit (1-5) instead of binary 0/1, rewarding partial correctness
  - Four orthogonal dimensions beyond faithfulness alone
  - Sliding window for multi-turn conversation degradation analysis
  - Normalised 0-1 output for backward compat with existing metrics

Dimensions
----------
faithfulness  : Is the answer grounded in the retrieved context?
relevancy     : Does the answer address the question?
completeness  : Does the answer cover all aspects of the question?
coherence     : Is the reasoning chain clear and logically consistent?
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rubric prompt templates  (1 = worst, 5 = best)
# ---------------------------------------------------------------------------

_RUBRIC = {
    "faithfulness": """\
根据检索到的【上下文】，对以下【回答】的忠实度打分（1-5分）：

5 = 回答完全基于上下文，无任何幻觉
4 = 主要基于上下文，有极少量无害推断
3 = 大部分基于上下文，有明显但合理的推断
2 = 约一半内容超出上下文范围
1 = 基本脱离上下文，大量捏造

只返回一个整数（1/2/3/4/5），不要解释。

上下文：{context}
问题：{question}
回答：{answer}""",

    "relevancy": """\
对以下【回答】回答【问题】的相关性打分（1-5分）：

5 = 完全切题，精准回答了问题的全部意图
4 = 基本切题，覆盖了问题的主要意图
3 = 部分切题，回答了问题的某个方面
2 = 轻微偏题，与问题有关联但未真正回答
1 = 完全偏题或拒绝回答

只返回一个整数（1/2/3/4/5），不要解释。

问题：{question}
回答：{answer}""",

    "completeness": """\
对以下【回答】是否完整覆盖了【问题】所有要点打分（1-5分）：

5 = 全面覆盖，无遗漏
4 = 覆盖了主要要点，有少量次要遗漏
3 = 覆盖了约一半要点
2 = 仅覆盖一个次要方面
1 = 几乎没有覆盖任何要点

只返回一个整数（1/2/3/4/5），不要解释。

问题：{question}
回答：{answer}""",

    "coherence": """\
对以下【回答】的逻辑连贯性和表达清晰度打分（1-5分）：

5 = 逻辑严密，层次清晰，结论有据可查
4 = 基本连贯，偶有跳跃但不影响理解
3 = 存在一定逻辑断层，需要读者自行补全
2 = 逻辑混乱，推断跳跃，难以跟随
1 = 自相矛盾或完全无逻辑

只返回一个整数（1/2/3/4/5），不要解释。

问题：{question}
回答：{answer}""",
}

DIMENSIONS = list(_RUBRIC.keys())


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RubricScore:
    faithfulness: int   # 1-5
    relevancy: int      # 1-5
    completeness: int   # 1-5
    coherence: int      # 1-5

    @property
    def mean(self) -> float:
        return (self.faithfulness + self.relevancy + self.completeness + self.coherence) / 4

    @property
    def normalised(self) -> float:
        """Scale mean to 0-1 for backward compat with existing metrics."""
        return (self.mean - 1) / 4

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mean"] = round(self.mean, 2)
        d["normalised"] = round(self.normalised, 3)
        return d


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

async def _score_dimension(
    dimension: str,
    question: str,
    answer: str,
    context: str,
    client: "AsyncOpenAI",
    model: str,
) -> int:
    """Call LLM for a single rubric dimension. Returns 1-5."""
    from config import DEEPSEEK_MODEL
    model = model or DEEPSEEK_MODEL
    prompt = _RUBRIC[dimension].format(
        context=context[:2000],
        question=question,
        answer=answer,
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=5,
        )
        raw = resp.choices[0].message.content.strip()
        match = re.search(r"[1-5]", raw)
        return int(match.group()) if match else 3
    except Exception:
        return 3  # neutral fallback


async def score_response(
    question: str,
    answer: str,
    context: str,
    client: "AsyncOpenAI",
    model: str = "",
    dimensions: list[str] | None = None,
) -> RubricScore:
    """
    Score a single (question, answer, context) triple across all rubric dimensions.

    Parameters
    ----------
    dimensions : subset of DIMENSIONS to score; defaults to all four.
    """
    dims = dimensions or DIMENSIONS
    scores_list = await asyncio.gather(*[
        _score_dimension(d, question, answer, context, client, model)
        for d in dims
    ])
    scores = dict(zip(dims, scores_list))
    # Fill unscored dims with neutral 3
    return RubricScore(
        faithfulness=scores.get("faithfulness", 3),
        relevancy=scores.get("relevancy", 3),
        completeness=scores.get("completeness", 3),
        coherence=scores.get("coherence", 3),
    )


# ---------------------------------------------------------------------------
# Sliding window — multi-turn degradation
# ---------------------------------------------------------------------------

async def score_conversation(
    turns: list[dict],
    client: "AsyncOpenAI",
    model: str = "",
    window: int = 3,
) -> dict:
    """
    Score answer quality across conversation turns using a sliding window.

    Parameters
    ----------
    turns  : list of {"question": str, "answer": str, "context": str}
    window : size of the sliding window for rolling average

    Returns
    -------
    {
        "per_turn": [{"turn": 1, "score": RubricScore.to_dict(), ...}],
        "rolling_mean": [float],   # window-averaged normalised scores
        "degradation": float,      # score[last] - score[first], negative = degraded
    }
    """
    per_turn = []
    for i, turn in enumerate(turns):
        rubric = await score_response(
            question=turn["question"],
            answer=turn["answer"],
            context=turn.get("context", ""),
            client=client,
            model=model,
        )
        per_turn.append({"turn": i + 1, **rubric.to_dict()})

    normalised = [t["normalised"] for t in per_turn]

    # Rolling mean
    rolling = []
    for i in range(len(normalised)):
        start = max(0, i - window + 1)
        rolling.append(round(sum(normalised[start: i + 1]) / (i - start + 1), 3))

    degradation = round(normalised[-1] - normalised[0], 3) if len(normalised) >= 2 else 0.0

    return {
        "per_turn": per_turn,
        "rolling_mean": rolling,
        "degradation": degradation,
        "turn_count": len(turns),
        "window": window,
    }
