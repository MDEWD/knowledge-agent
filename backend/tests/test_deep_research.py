"""
Unit tests for the DeepResearch module.

覆盖:
1. SEARCH_BACKEND 三种模式路由出不同的工具集
2. DeepResearchOrchestrator 可在 mock client 下实例化
3. evaluator._coerce_int 边界值
4. evaluator 数据类 EvaluationResult.average 计算
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import config
from agents.deep_research.evaluator import EvaluationResult, _coerce_int
from agents.deep_research.model_config import DeepResearchModels
from agents.deep_research.search_router import (
    KB_SEARCH_TOOL,
    TAVILY_SEARCH_TOOL,
    THINK_TOOL,
    get_sub_researcher_tools,
)


def test_streaming_endpoints_have_data_path_configured(monkeypatch):
    """Agent streaming generators require the shared data directory."""
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(config, "QWEN_API_KEY", "test-key")
    import app

    assert app.DATA_PATH == config.DATA_PATH


def test_deep_follow_up_builds_bounded_conversation_context():
    """再次追问应携带既有报告，同时限制历史长度避免上下文无限膨胀。"""
    from agents.deep_research.context import build_deep_research_task

    enriched = build_deep_research_task(
        "哪些细分方向风险最高？",
        [{
            "question": "分析下半年 A 股半导体趋势",
            "answer": "旧" * 20_000,
        }],
    )

    assert "分析下半年 A 股半导体趋势" in enriched
    assert "哪些细分方向风险最高？" in enriched
    assert "基于既有深度研究继续追问" in enriched
    assert len(enriched) < 15_000


# ---------------------------------------------------------------------------
# 1. SEARCH_BACKEND 路由
# ---------------------------------------------------------------------------

def test_search_backend_kb_only():
    """kb_only 只暴露 KB 检索 + think_tool。"""
    prev = config.SEARCH_BACKEND
    config.SEARCH_BACKEND = "kb_only"
    try:
        tools, names = get_sub_researcher_tools()
    finally:
        config.SEARCH_BACKEND = prev
    assert names == ["search_knowledge_base", "think_tool"]
    assert KB_SEARCH_TOOL in tools
    assert TAVILY_SEARCH_TOOL not in tools
    assert THINK_TOOL in tools


def test_search_backend_web_only():
    """web_only 只暴露 Tavily + think_tool。"""
    prev = config.SEARCH_BACKEND
    config.SEARCH_BACKEND = "web_only"
    try:
        tools, names = get_sub_researcher_tools()
    finally:
        config.SEARCH_BACKEND = prev
    assert names == ["tavily_search", "think_tool"]
    assert TAVILY_SEARCH_TOOL in tools
    assert KB_SEARCH_TOOL not in tools


def test_search_backend_hybrid():
    """hybrid 三个工具都暴露。"""
    prev = config.SEARCH_BACKEND
    config.SEARCH_BACKEND = "hybrid"
    try:
        tools, names = get_sub_researcher_tools()
    finally:
        config.SEARCH_BACKEND = prev
    assert names == ["search_knowledge_base", "tavily_search", "think_tool"]
    assert KB_SEARCH_TOOL in tools
    assert TAVILY_SEARCH_TOOL in tools
    assert THINK_TOOL in tools


def test_search_backend_invalid_falls_back_to_kb_only():
    """未知值兜底为 kb_only。"""
    prev = config.SEARCH_BACKEND
    config.SEARCH_BACKEND = "weird_value"
    try:
        _, names = get_sub_researcher_tools()
    finally:
        config.SEARCH_BACKEND = prev
    assert names == ["search_knowledge_base", "think_tool"]


def test_search_backend_none_falls_back_to_kb_only():
    """None 兜底为 kb_only。"""
    prev = config.SEARCH_BACKEND
    config.SEARCH_BACKEND = None
    try:
        _, names = get_sub_researcher_tools()
    finally:
        config.SEARCH_BACKEND = prev
    assert names == ["search_knowledge_base", "think_tool"]


# ---------------------------------------------------------------------------
# 2. Orchestrator 实例化
# ---------------------------------------------------------------------------

def test_orchestrator_instantiation_with_mock_client(monkeypatch):
    """DeepResearchOrchestrator 在 mock client 下应可正常实例化。"""
    from agents.deep_research.orchestrator import DeepResearchOrchestrator
    from harness.retry import RetryPolicy, CircuitBreaker

    for role in (
        "DRAFT", "SUPERVISOR", "RESEARCHER_MAIN", "RESEARCHER_SUMMARIZER",
        "RESEARCHER_COMPRESSOR", "RED_TEAM", "EVALUATOR", "WRITER",
    ):
        monkeypatch.delenv(f"DEEP_RESEARCH_{role}_MODEL", raising=False)

    client = MagicMock()
    orch = DeepResearchOrchestrator(
        client,
        model="deepseek-chat",
        policy=RetryPolicy(max_attempts=1, base_delay=0.1),
        circuit=CircuitBreaker(failure_threshold=1, recovery_timeout=1.0),
    )
    assert orch.model == "deepseek-chat"
    assert orch.models.draft == "deepseek-chat"
    assert orch._sub_researcher is not None
    assert orch._sub_researcher._tools, "SubResearcher 应有可用工具"


def test_orchestrator_uses_role_specific_models():
    from agents.deep_research.orchestrator import DeepResearchOrchestrator

    models = DeepResearchModels(
        draft="draft-model",
        supervisor="supervisor-model",
        researcher_main="researcher-model",
        researcher_summarizer="summarizer-model",
        researcher_compressor="compressor-model",
        red_team="red-team-model",
        evaluator="evaluator-model",
        writer="writer-model",
    )
    orch = DeepResearchOrchestrator(MagicMock(), "fallback-model", models=models)

    assert orch.models == models
    assert orch._sub_researcher.model == "researcher-model"
    assert orch._sub_researcher.summarizer_model == "summarizer-model"
    assert orch._sub_researcher.compressor_model == "compressor-model"


def test_role_models_fall_back_to_default(monkeypatch):
    roles = [
        "DRAFT",
        "SUPERVISOR",
        "RESEARCHER_MAIN",
        "RESEARCHER_SUMMARIZER",
        "RESEARCHER_COMPRESSOR",
        "RED_TEAM",
        "EVALUATOR",
        "WRITER",
    ]
    for role in roles:
        monkeypatch.delenv(f"DEEP_RESEARCH_{role}_MODEL", raising=False)

    models = DeepResearchModels.from_env("fallback-model")

    assert set(models.__dict__.values()) == {"fallback-model"}


def test_role_models_load_deepseek_v4_routing(monkeypatch):
    flash_roles = [
        "DRAFT",
        "SUPERVISOR",
        "RESEARCHER_MAIN",
        "RESEARCHER_SUMMARIZER",
        "RESEARCHER_COMPRESSOR",
    ]
    pro_roles = ["RED_TEAM", "EVALUATOR", "WRITER"]
    for role in flash_roles:
        monkeypatch.setenv(f"DEEP_RESEARCH_{role}_MODEL", "deepseek-v4-flash")
    for role in pro_roles:
        monkeypatch.setenv(f"DEEP_RESEARCH_{role}_MODEL", "deepseek-v4-pro")

    models = DeepResearchModels.from_env("fallback-model")

    assert {getattr(models, role.lower()) for role in flash_roles} == {
        "deepseek-v4-flash"
    }
    assert {getattr(models, role.lower()) for role in pro_roles} == {
        "deepseek-v4-pro"
    }


@pytest.mark.asyncio
async def test_red_team_json_response_request_explicitly_mentions_json():
    """DeepSeek requires a JSON instruction whenever json_object mode is enabled."""
    from agents.deep_research.red_team import red_team_review
    from harness.retry import RetryPolicy

    captured_request = {}

    async def create(**kwargs):
        captured_request.update(kwargs)
        message_text = " ".join(
            str(message.get("content", ""))
            for message in kwargs.get("messages", [])
        ).lower()
        if "json" not in message_text:
            raise RuntimeError(
                "Prompt must contain the word 'json' to use json_object"
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(
                    content='{"pass": true, "critiques": []}'
                )
            )],
            usage=None,
        )

    client = MagicMock()
    client.chat.completions.create = create

    findings = await red_team_review(
        client,
        "deepseek-v4-pro",
        research_brief="分析研究问题",
        draft_report="这是一份足够长的报告草稿。" * 10,
        evidence=[],
        policy=RetryPolicy(max_attempts=1, base_delay=0),
    )

    assert findings == []
    assert captured_request["response_format"] == {"type": "json_object"}


def test_assistant_message_preserves_reasoning_content():
    from agents.deep_research.orchestrator import _assistant_message_payload

    message = SimpleNamespace(
        content="final answer",
        reasoning_content="internal reasoning",
        tool_calls=[],
    )

    assert _assistant_message_payload(message) == {
        "role": "assistant",
        "content": "final answer",
        "reasoning_content": "internal reasoning",
    }


@pytest.mark.asyncio
async def test_orchestrator_llm_call_has_hard_timeout():
    from agents.deep_research.orchestrator import DeepResearchOrchestrator

    async def slow_create(**kwargs):
        await asyncio.sleep(0.05)

    client = MagicMock()
    client.chat.completions.create = slow_create
    orch = DeepResearchOrchestrator(
        client,
        "fallback-model",
        llm_timeout_seconds=0.001,
    )

    with pytest.raises(asyncio.TimeoutError):
        await orch._llm(model="test-model", messages=[])


@pytest.mark.asyncio
async def test_write_draft_uses_plain_markdown_response():
    """长 Markdown 不应塞进 JSON，避免输出截断后 JSON 解析失败。"""
    from agents.deep_research.orchestrator import DeepResearchOrchestrator

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="# 完整报告\n\n正文"))]
    )
    orch = DeepResearchOrchestrator(MagicMock(), "fallback-model")
    orch._llm = AsyncMock(return_value=response)
    orch._llm_json = AsyncMock(side_effect=AssertionError("draft must not use JSON"))

    draft = await orch._write_draft("研究简报")

    assert draft == "# 完整报告\n\n正文"
    orch._llm.assert_awaited_once()
    assert orch._llm.await_args.kwargs["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_all_conduct_research_calls_receive_results_with_bounded_concurrency(
    monkeypatch,
):
    """并发上限只限制同时运行数，不能丢弃多余 tool_call。"""
    import agents.deep_research.orchestrator as orchestrator_module
    from agents.deep_research.orchestrator import DeepResearchOrchestrator

    monkeypatch.setattr(orchestrator_module, "DEEP_RESEARCH_MAX_CONCURRENT", 2)
    active = 0
    max_active = 0
    completed_topics: list[str] = []

    class FakeSubResearcher:
        async def run_stream(self, topic):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            try:
                await asyncio.sleep(0.01)
                completed_topics.append(topic)
                yield {"type": "sub_agent_done", "result": f"result:{topic}"}
            finally:
                active -= 1

    calls = [
        SimpleNamespace(
            id=f"call-{i}",
            function=SimpleNamespace(
                arguments=f'{{"research_topic": "topic-{i}"}}'
            ),
        )
        for i in range(5)
    ]
    orch = DeepResearchOrchestrator(MagicMock(), "fallback-model")
    orch._sub_researcher = FakeSubResearcher()

    events = [
        event
        async for event in orch._run_concurrent_sub_researchers(calls)
    ]
    results = [
        event for event in events
        if event.get("type") == "__sub_researcher_result__"
    ]

    assert [result["tool_call_id"] for result in results] == [
        f"call-{i}" for i in range(5)
    ]
    assert completed_topics == [f"topic-{i}" for i in range(5)]
    assert max_active == 2


@pytest.mark.asyncio
async def test_supervisor_replies_to_every_tool_call_before_next_llm_turn(
    monkeypatch,
):
    """未知或未执行工具也必须收到 ToolMessage，保持 OpenAI 消息协议完整。"""
    import agents.deep_research.orchestrator as orchestrator_module
    from agents.deep_research.orchestrator import DeepResearchOrchestrator

    monkeypatch.setattr(orchestrator_module, "DEEP_RESEARCH_MAX_ITERATIONS", 2)

    def tool_call(call_id: str, name: str):
        return SimpleNamespace(
            id=call_id,
            function=SimpleNamespace(name=name, arguments="{}"),
        )

    first_calls = [
        tool_call("known-call", "think_tool"),
        tool_call("unknown-call", "Conduct_Research"),
    ]
    first_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content="",
            reasoning_content=None,
            tool_calls=first_calls,
        ))]
    )
    final_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content="done",
            reasoning_content=None,
            tool_calls=[],
        ))]
    )
    turns = 0

    async def supervisor_step(messages, **kwargs):
        nonlocal turns
        turns += 1
        if turns == 1:
            return first_response

        assistant_index = max(
            i for i, message in enumerate(messages)
            if message.get("role") == "assistant" and message.get("tool_calls")
        )
        expected_ids = {
            call["id"] for call in messages[assistant_index]["tool_calls"]
        }
        responded_ids = {
            message.get("tool_call_id")
            for message in messages[assistant_index + 1:]
            if message.get("role") == "tool"
        }
        assert responded_ids == expected_ids
        return final_response

    orch = DeepResearchOrchestrator(MagicMock(), "fallback-model")
    orch._supervisor_step = supervisor_step

    events = [
        event async for event in orch._run_supervisor_loop(
            task="task",
            brief="brief",
            draft="draft",
            run_id="run-id",
        )
    ]

    assert turns == 2
    assert not [event for event in events if event.get("type") == "error"]


@pytest.mark.asyncio
async def test_red_team_feedback_does_not_interrupt_tool_response_block(monkeypatch):
    """Red Team system context must not be inserted between tool response messages."""
    import agents.deep_research.orchestrator as orchestrator_module
    from agents.deep_research.orchestrator import DeepResearchOrchestrator

    monkeypatch.setattr(orchestrator_module, "DEEP_RESEARCH_MAX_ITERATIONS", 2)
    monkeypatch.setattr(
        orchestrator_module,
        "evaluate_draft_quality",
        AsyncMock(return_value=EvaluationResult(8, 8, 8, "good")),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "red_team_review",
        AsyncMock(return_value=[
            __import__("agents.deep_research.state", fromlist=["Critique"]).Critique(
                category="logic",
                severity="medium",
                problem="需要补充风险证据",
            )
        ]),
    )

    calls = [
        SimpleNamespace(
            id="think-call",
            function=SimpleNamespace(name="think_tool", arguments="{}"),
        ),
        SimpleNamespace(
            id="refine-call",
            function=SimpleNamespace(name="refine_draft_report", arguments="{}"),
        ),
    ]
    first_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content="", reasoning_content=None, tool_calls=calls,
        ))]
    )
    final_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content="done", reasoning_content=None, tool_calls=[],
        ))]
    )
    turns = 0

    async def supervisor_step(messages, **kwargs):
        nonlocal turns
        turns += 1
        if turns == 1:
            return first_response

        assistant_index = max(
            i for i, message in enumerate(messages)
            if message.get("role") == "assistant" and message.get("tool_calls")
        )
        following = messages[assistant_index + 1:]
        assert [message.get("role") for message in following[:2]] == ["tool", "tool"]
        assert {message.get("tool_call_id") for message in following[:2]} == {
            "think-call", "refine-call",
        }
        return final_response

    orch = DeepResearchOrchestrator(MagicMock(), "fallback-model")
    orch._supervisor_step = supervisor_step
    orch._refine_draft = AsyncMock(return_value="updated draft")

    events = [
        event async for event in orch._run_supervisor_loop(
            task="task", brief="brief", draft="draft", run_id="run-id",
        )
    ]

    assert turns == 2
    assert not [event for event in events if event.get("type") == "error"]


def test_vector_store_initializes_chroma_once_under_concurrency(monkeypatch):
    from storage import vector_store

    calls = 0
    collection = MagicMock()
    start = threading.Barrier(8)

    class FakeClient:
        def get_or_create_collection(self, *args, **kwargs):
            return collection

    def fake_persistent_client(*args, **kwargs):
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        return FakeClient()

    monkeypatch.setattr(vector_store, "_collection", None)
    monkeypatch.setattr(vector_store, "_client", None)
    monkeypatch.setattr(vector_store, "_embedding_function", None)
    monkeypatch.setattr(vector_store.chromadb, "PersistentClient", fake_persistent_client)
    monkeypatch.setattr(
        vector_store.embedding_functions,
        "SentenceTransformerEmbeddingFunction",
        lambda **kwargs: MagicMock(),
    )

    def get_collection():
        start.wait()
        return vector_store._get_collection()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: get_collection(), range(8)))

    assert calls == 1
    assert all(result is collection for result in results)


def test_vector_search_falls_back_to_bm25_when_chroma_is_unavailable(monkeypatch):
    from storage import vector_store

    monkeypatch.setattr(
        vector_store,
        "_get_collection",
        MagicMock(side_effect=RuntimeError("chroma unavailable")),
    )
    monkeypatch.setattr(
        vector_store.bm25_store,
        "search",
        lambda query, n: [("doc-1", 1.0)],
    )
    monkeypatch.setattr(
        vector_store.bm25_store,
        "get_doc_by_id",
        lambda doc_id: {
            "text": "BM25 fallback result",
            "metadata": {"title": "Fallback", "url": "local://1"},
        },
    )

    assert vector_store.search("query", n_results=3) == [
        {
            "content": "BM25 fallback result",
            "metadata": {"title": "Fallback", "url": "local://1"},
        }
    ]


@pytest.mark.asyncio
async def test_tavily_search_streams_source_events(monkeypatch):
    from agents.deep_research import search_router

    client_init = {}

    class FakeTavilyClient:
        def __init__(self, **kwargs):
            client_init.update(kwargs)

        def search(self, **kwargs):
            return {
                "results": [
                    {
                        "title": "Semiconductor outlook",
                        "url": "https://example.com/outlook",
                        "content": "Short source summary",
                    }
                ]
            }

    monkeypatch.setattr(search_router._config, "TAVILY_API_KEY", "test-key")
    monkeypatch.setitem(
        sys.modules,
        "tavily",
        SimpleNamespace(TavilyClient=FakeTavilyClient),
    )
    events = []

    async def collect(event):
        events.append(event)

    async def summarize(prompt):
        return "summarized"

    result = await search_router._tavily_search_impl(
        "A股半导体趋势",
        llm_call=summarize,
        event_sink=collect,
    )

    assert "Semiconductor outlook" in result
    assert client_init["api_base_url"] == search_router._config.TAVILY_BASE_URL
    assert "base_url" not in client_init
    assert {
        key: events[0][key]
        for key in ("type", "agent", "query", "title", "url", "snippet", "status")
    } == {
        "type": "research_source",
        "agent": "SubResearcher",
        "query": "A股半导体趋势",
        "title": "Semiconductor outlook",
        "url": "https://example.com/outlook",
        "snippet": "Short source summary",
        "status": "found",
    }
    assert events[0]["source_id"].startswith("src_")
    assert events[0]["authority_score"] > 0
    assert events[0]["evidence"]["url"] == "https://example.com/outlook"


# ---------------------------------------------------------------------------
# 3. Evaluator 工具函数
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (5, 5),
    ("7", 7),
    (11, 10),       # 上限截断
    (-3, 0),        # 下限截断
    ("abc", 0),     # 非法字符串
    (None, 0),      # None
    (8.7, 8),       # 浮点转 int
])
def test_coerce_int(raw, expected):
    assert _coerce_int(raw) == expected


def test_evaluation_result_average():
    """EvaluationResult.average 应为三维均分。"""
    r = EvaluationResult(
        comprehensiveness_score=8,
        accuracy_score=7,
        coherence_score=9,
        reason="ok",
    )
    assert r.average == pytest.approx(8.0, rel=1e-3)


def test_evaluation_result_zero_average():
    r = EvaluationResult(0, 0, 0, "fail")
    assert r.average == 0.0
