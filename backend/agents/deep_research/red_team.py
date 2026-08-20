"""Red Team 对抗智能体: 找出报告草稿的逻辑缺陷、漏洞和不完善的地方。

移植自原 DeepResearch 项目, 适配为纯 AsyncOpenAI 调用。
关键约束:
  - MAX_CRITIC 上限, 防止红队和 supervisor 之间无限循环;
  - 草稿过短(< MIN_DRAFT_LEN)直接跳过;
  - 输出"PASS"或过短视为无问题。
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from agents.deep_research.prompts import RED_TEAM_PROMPT
from agents.deep_research.budget import ResearchBudget
from agents.deep_research.evidence import Evidence
from agents.deep_research.model_runtime import (
    apply_role_options,
    collect_streamed_text_completion,
)
from agents.deep_research.state import (
    Critique,
    CritiqueCategory,
    CritiqueSeverity,
)
from config import DEEP_RESEARCH_RED_TEAM_MAX
from harness.retry import CircuitBreaker, RetryPolicy, async_retry

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

MIN_DRAFT_LEN = 50
MIN_CRITIC = 20


async def red_team_critique(
    client: "AsyncOpenAI",
    model: str,
    *,
    research_brief: str,
    draft_report: str,
    critique_nums: int = 0,
    policy: RetryPolicy | None = None,
    circuit: CircuitBreaker | None = None,
    timeout_seconds: float = 120.0,
    evidence: list[Evidence] | None = None,
    budget: ResearchBudget | None = None,
    iteration: int = 0,
) -> str | None:
    """对草稿做对抗挑刺。

    返回:
      - None: 视为通过(无重要问题);
      - str:  最关键可操作的批评意见(供 supervisor 注入为 System Message)。
    """
    findings = await red_team_review(
        client,
        model,
        research_brief=research_brief,
        draft_report=draft_report,
        evidence=evidence or [],
        critique_nums=critique_nums,
        policy=policy,
        circuit=circuit,
        timeout_seconds=timeout_seconds,
        budget=budget,
        iteration=iteration,
    )
    if not findings:
        return None
    return "\n".join(
        f"[{item.severity.value}/{item.category.value}] {item.problem}；修复：{item.remediation}"
        for item in findings
    )


async def red_team_review(
    client: "AsyncOpenAI",
    model: str,
    *,
    research_brief: str,
    draft_report: str,
    evidence: list[Evidence],
    critique_nums: int = 0,
    policy: RetryPolicy | None = None,
    circuit: CircuitBreaker | None = None,
    timeout_seconds: float = 120.0,
    budget: ResearchBudget | None = None,
    iteration: int = 0,
) -> list[Critique]:
    """Return structured, evidence-grounded Critiques."""
    if (
        critique_nums >= DEEP_RESEARCH_RED_TEAM_MAX
        or not draft_report
        or len(draft_report) < MIN_DRAFT_LEN
    ):
        return []

    evidence_context = "\n\n".join(
        f"[{item.source_id}] {item.title}\nURL: {item.url}\n摘要: {item.snippet[:1200]}"
        for item in evidence
    ) or "(本轮尚未收集到可验证证据)"

    prompt = RED_TEAM_PROMPT.format(
        research_brief=research_brief,
        draft_report=draft_report,
        evidence_context=evidence_context,
    )

    policy = policy or RetryPolicy(max_attempts=3, base_delay=1.0)

    async def _call():
        request_options = apply_role_options({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "max_tokens": 8192,
            "response_format": {"type": "json_object"},
        }, "red_team")
        return await collect_streamed_text_completion(
            client,
            request_options,
            timeout_seconds=timeout_seconds,
        )

    resp = await async_retry(_call, policy=policy, circuit=circuit, label="RedTeam/llm")
    content = resp.content or ""
    if budget is not None:
        budget.charge_llm(
            role="red_team",
            model=model,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
        )
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        if "PASS" in content or len(content) < MIN_CRITIC:
            return []
        data = {"critiques": [{
            "category": "logic",
            "severity": "medium",
            "problem": content,
            "remediation": "重新核验并修订该问题",
        }]}

    findings: list[Critique] = []
    for item in data.get("critiques", [])[:3]:
        try:
            category = CritiqueCategory(item.get("category", "logic"))
        except ValueError:
            category = CritiqueCategory.LOGIC
        try:
            severity = CritiqueSeverity(item.get("severity", "medium"))
        except ValueError:
            severity = CritiqueSeverity.MEDIUM
        problem = str(item.get("problem", "")).strip()
        if not problem:
            continue
        findings.append(Critique(
            category=category,
            severity=severity,
            claim=str(item.get("claim", "")),
            evidence_ids=[str(value) for value in item.get("evidence_ids", [])],
            problem=problem,
            remediation=str(item.get("remediation", "")),
            created_iteration=iteration,
        ))
    logger.info("[RED TEAM] structured critiques=%d", len(findings))
    return findings


def _usage_int(usage, field: str) -> int:
    value = getattr(usage, field, 0) if usage is not None else 0
    return int(value) if isinstance(value, (int, float)) else 0
