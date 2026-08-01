"""报告评估智能体(self-evolution): 用另一个 LLM 作为 Judge,
对草稿按 全面性 / 准确性 / 一致性 三维度打分, 输出结构化 EvaluationResult。

移植自原 DeepResearch 项目, 用 OpenAI JSON mode 而非 langchain 的
with_structured_output, 保持纯 openai 依赖。
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agents.deep_research.prompts import DRAFT_EVALUATOR_PROMPT
from agents.deep_research.budget import ResearchBudget, ResearchBudgetExceeded
from agents.deep_research.evidence import Evidence
from agents.deep_research.model_runtime import apply_role_options
from config import DEEP_RESEARCH_EVALUATOR_MAX_TOKENS
from harness.retry import CircuitBreaker, RetryPolicy, async_retry

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class EvaluatorResponseError(ValueError):
    """The model returned text, but no complete evaluator JSON object."""


class _EvaluatorRetryPolicy:
    """Retry malformed model output as well as transient transport errors."""

    def __init__(self, base: RetryPolicy) -> None:
        self.base = base
        self.max_attempts = base.max_attempts

    def delay_for(self, attempt: int) -> float:
        return self.base.delay_for(attempt)

    def is_retryable(self, exc: BaseException) -> bool:
        return isinstance(exc, EvaluatorResponseError) or self.base.is_retryable(exc)


@dataclass
class EvaluationResult:
    comprehensiveness_score: int   # 0-10
    accuracy_score: int            # 0-10
    coherence_score: int           # 0-10
    reason: str
    evidence_coverage: float = 0.0

    @property
    def average(self) -> float:
        return (self.comprehensiveness_score + self.accuracy_score + self.coherence_score) / 3


def _coerce_int(value, default: int = 0) -> int:
    try:
        v = int(value)
        return max(0, min(10, v))
    except (TypeError, ValueError):
        return default


async def evaluate_draft_quality(
    client: "AsyncOpenAI",
    model: str,
    *,
    research_brief: str,
    draft_report: str,
    policy: RetryPolicy | None = None,
    circuit: CircuitBreaker | None = None,
    timeout_seconds: float = 120.0,
    evidence: list[Evidence] | None = None,
    budget: ResearchBudget | None = None,
) -> EvaluationResult:
    """对草稿做三维度打分。LLM 调用失败时返回 0 分 + 错误原因。"""
    evidence_context = "\n\n".join(
        f"[{item.source_id}] {item.title}\nURL: {item.url}\n摘要: {item.snippet[:1000]}"
        for item in (evidence or [])
    ) or "(无结构化证据)"
    prompt = DRAFT_EVALUATOR_PROMPT.format(
        research_brief=research_brief,
        draft_report=draft_report,
        evidence_context=evidence_context,
    )
    policy = policy or RetryPolicy(max_attempts=3, base_delay=1.0)

    async def _call():
        request_options = apply_role_options({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": DEEP_RESEARCH_EVALUATOR_MAX_TOKENS,
            "response_format": {"type": "json_object"},
        }, "evaluator")
        resp = await asyncio.wait_for(
            client.chat.completions.create(**request_options),
            timeout=timeout_seconds,
        )
        if budget is not None:
            usage = getattr(resp, "usage", None)
            budget.charge_llm(
                role="evaluator",
                model=model,
                input_tokens=_usage_int(usage, "prompt_tokens"),
                output_tokens=_usage_int(usage, "completion_tokens"),
            )
        message = resp.choices[0].message
        candidates = [
            getattr(message, "content", None) or "",
            getattr(message, "reasoning_content", None) or "",
        ]
        errors: list[str] = []
        for candidate in candidates:
            if not candidate.strip():
                continue
            try:
                return _extract_json_object(candidate)
            except EvaluatorResponseError as exc:
                errors.append(str(exc))
        raise EvaluatorResponseError("；".join(errors) or "模型返回为空")

    try:
        data = await async_retry(
            _call,
            policy=_EvaluatorRetryPolicy(policy),
            circuit=circuit,
            label="Evaluator/llm",
        )
        result = EvaluationResult(
            comprehensiveness_score=_coerce_int(data.get("comprehensiveness_score")),
            accuracy_score=_coerce_int(data.get("accuracy_score")),
            coherence_score=_coerce_int(data.get("coherence_score")),
            reason=str(data.get("reason", "")),
            evidence_coverage=_coerce_float(data.get("evidence_coverage")),
        )
        logger.info(
            "[EVALUATOR] comprehensive=%d accuracy=%d coherence=%d avg=%.2f",
            result.comprehensiveness_score,
            result.accuracy_score,
            result.coherence_score,
            result.average,
        )
        return result
    except ResearchBudgetExceeded:
        raise
    except Exception as exc:
        logger.warning("[EVALUATOR] llm failed: %s — returning zero scores", exc)
        return EvaluationResult(0, 0, 0, f"评估失败: {exc}")


def _coerce_float(value, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _extract_json_object(raw: str) -> dict:
    """Extract the first complete JSON object from plain or wrapped model text."""
    text = (raw or "").strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            required = {
                "comprehensiveness_score",
                "accuracy_score",
                "coherence_score",
            }
            if required <= set(value):
                return value
    preview = " ".join(text.split())[:160]
    raise EvaluatorResponseError(
        f"未找到完整评分 JSON" + (f": {preview}" if preview else "：模型返回为空")
    )


def _usage_int(usage, field: str) -> int:
    value = getattr(usage, field, 0) if usage is not None else 0
    return int(value) if isinstance(value, (int, float)) else 0
