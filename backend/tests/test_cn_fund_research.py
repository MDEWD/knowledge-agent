from __future__ import annotations

import pytest

from agent_skills.loader import FileSkillRegistry
from agents.deep_research import search_router
from fund_research.metrics import calculate_fund_metrics


def test_skill_registry_routes_only_public_web_fund_skill():
    skills = FileSkillRegistry().match("研究510300最近三年的ETF收益和最大回撤")
    assert [item.name for item in skills] == ["cn-fund-research"]
    prompt = FileSkillRegistry().prompt_for("分析公募基金经理")
    assert "cn-fund-research" in prompt
    assert "付费 Token" in prompt


def test_fund_task_gets_web_search_without_paid_data_tools(monkeypatch):
    monkeypatch.setattr(search_router._config, "SEARCH_BACKEND", "kb_only")
    monkeypatch.setattr(search_router._config, "CN_FUND_ENABLE_WEB_SEARCH", True)
    _, names = search_router.get_sub_researcher_tools("研究510300 ETF")
    assert set(names) == {"search_knowledge_base", "tavily_search", "think_tool"}


def test_metrics_library_remains_deterministic_and_date_aligned():
    fund = [
        {"date": "20240101", "value": 100},
        {"date": "20240102", "value": 80},
        {"date": "20240103", "value": 120},
    ]
    benchmark = [
        {"date": "20240101", "value": 100},
        {"date": "20240103", "value": 110},
        {"date": "20240104", "value": 999},
    ]
    result = calculate_fund_metrics(fund, benchmark, annual_risk_free_rate=0)
    assert result["cumulative_return"] == pytest.approx(0.2)
    assert result["max_drawdown"] == pytest.approx(-0.2)
    assert result["benchmark"]["observation_count"] == 2
    assert result["benchmark"]["excess_return"] == pytest.approx(0.1)
