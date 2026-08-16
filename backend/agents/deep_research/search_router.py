"""DeepResearch conduct_research 阶段的检索路由层。

根据 config.SEARCH_BACKEND 决定子 Agent 实际可用的工具集:
  - kb_only  : 仅暴露 search_knowledge_base (复用 storage.vector_store.search)
  - web_only : 仅暴露 tavily_search (调 Tavily API, 长文做 LLM 摘要)
  - hybrid   : 两个工具都暴露

所有工具均符合 OpenAI function-calling schema, 由 sub_researcher 调用。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

import config as _config
from agent_skills.loader import is_cn_fund_research
from agents.deep_research.evidence import Evidence
from agents.deep_research.prompts import SUMMARIZE_PROMPT
from agents.deep_research.search_policy import SearchQualityPolicy

logger = logging.getLogger(__name__)

# 网页摘要的字符上限(避免把超长正文塞给 LLM)
_MAX_RAW_FOR_SUMMARY = 8000


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------

def _kb_search_impl(query: str, n_results: int = 8) -> str:
    """在个人知识库做混合检索。复用现有 vector_store.search (ChromaDB+BM25+RRF)。"""
    from storage.vector_store import search as kb_search

    results = kb_search(query, n_results=n_results)
    if not results:
        return "知识库中未找到相关内容。"

    chunks = [
        f"[来源:《{r.get('metadata', {}).get('title', '')}》]\n{r.get('content', '')}"
        for r in results
    ]
    return "\n\n---\n\n".join(chunks)


async def _tavily_search_impl(
    query: str,
    *,
    llm_call: Callable[[str], Awaitable[str]],
    max_results: int | None = None,
    event_sink: Callable[[dict], Awaitable[None]] | None = None,
    search_policy: SearchQualityPolicy | None = None,
) -> str:
    """调 Tavily 联网搜索并对长文做 LLM 摘要。

    llm_call: 异步函数,输入 prompt 返回 LLM 文本响应(用于网页摘要)。
    """
    if not _config.TAVILY_API_KEY:
        return "[Tavily 未配置] 请在 .env 中设置 TAVILY_API_KEY 以启用联网搜索。"
    if search_policy is not None and not search_policy.accept_query(query):
        return "[跳过重复搜索] 本次 Research Run 已执行过等价 Query。"

    try:
        from tavily import TavilyClient  # type: ignore
    except ImportError as exc:
        return f"[tavily-python 未安装] {exc}"

    try:
        # tavily 同步客户端, 放到线程池里跑, 避免阻塞 event loop
        client = TavilyClient(
            api_key=_config.TAVILY_API_KEY,
            api_base_url=_config.TAVILY_BASE_URL,
        )
        resp = await asyncio.to_thread(
            client.search,
            query=query,
            max_results=max_results or _config.TAVILY_MAX_RESULTS,
            topic=_config.TAVILY_TOPIC,
            include_raw_content=_config.TAVILY_LLM_SUMMARIZE,
            timeout=_config.TAVILY_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.error("[tavily_search] query=%s failed: %s", query, exc)
        return f"[Tavily 搜索失败] {exc}"

    results = resp.get("results", []) if isinstance(resp, dict) else []
    if not results:
        return "未找到相关网页。"

    # 去重
    unique: dict[str, dict] = {}
    for r in results:
        url = r.get("url", "")
        if url and url not in unique:
            unique[url] = r

    evidence_items: list[tuple[Evidence, dict]] = []
    for url, result in unique.items():
        item = Evidence.create(
            url=url,
            title=result.get("title", "") or url,
            query=query,
            # The found event may show a short preview in the UI, but only the
            # post-sanitization summary is admitted to the Evidence ledger.
            snippet="",
            # Raw pages can be huge or contain content rejected by the model
            # provider. Keep them local to this function; checkpoints only need
            # the bounded evidence excerpt.
            raw_content="",
            published_at=(
                result.get("published_date")
                or result.get("published_at")
                or result.get("date")
            ),
            source_type=result.get("source_type", "web"),
            metadata={"provider": "tavily", "provider_score": result.get("score")},
        )
        (search_policy or SearchQualityPolicy()).score(item)
        if search_policy is not None:
            if not search_policy.accept_url(item.url):
                continue
        evidence_items.append((item, result))

    # 优先处理权威且新鲜的来源，使有限摘要预算先覆盖高质量 Evidence。
    evidence_items.sort(
        key=lambda pair: (
            pair[0].authority_score * 0.65 + pair[0].freshness_score * 0.35
        ),
        reverse=True,
    )

    if not evidence_items:
        return "未发现新的唯一来源（结果已在本次 Research Run 中检索过）。"

    async def _emit_source(item: Evidence, *, status: str, snippet: str) -> None:
        if event_sink is None:
            return
        await event_sink({
            "type": "research_source",
            "agent": "SubResearcher",
            "query": item.query,
            "title": item.title,
            "url": item.url,
            "snippet": " ".join((snippet or "").split())[:500],
            "status": status,
            "source_id": item.source_id,
            "published_at": item.published_at,
            "source_type": item.source_type,
            "authority_score": item.authority_score,
            "freshness_score": item.freshness_score,
            "evidence": item.to_dict(),
        })

    # Surface the source list immediately, before potentially slow LLM
    # summarization starts.
    for item, result in evidence_items:
        await _emit_source(
            item,
            status="found",
            snippet=result.get("content", "") or (result.get("raw_content") or "")[:500],
        )

    # 对长文并发做摘要
    async def _process(i_item: tuple[int, Evidence, dict]) -> str:
        i, item, r = i_item
        title = item.title
        raw = r.get("raw_content") or r.get("content", "")
        if _config.TAVILY_LLM_SUMMARIZE and raw and len(raw) > 2000:
            try:
                import datetime as _dt
                summary = await llm_call(
                    SUMMARIZE_PROMPT.format(
                        webpage_content=raw[:_MAX_RAW_FOR_SUMMARY],
                        date=_dt.date.today().isoformat(),
                    )
                )
            except Exception as exc:
                if _is_content_risk(exc):
                    logger.info(
                        "[tavily_search] source body isolated by provider content policy: %s",
                        item.url,
                    )
                    summary = "[该网页正文触发模型供应商内容安全策略，已隔离正文；仅保留标题与 URL。]"
                else:
                    logger.warning("[tavily_search] summarize failed: %s", exc)
                    summary = (r.get("content") or "")[:1000] or "[网页摘要暂时不可用]"
        else:
            summary = (r.get("content") or "")[:2000] or "(无正文摘要，仅保留来源链接)"
        item.snippet = summary
        await _emit_source(item, status="summarized", snippet=summary)
        return (
            f"--- EVIDENCE {item.source_id}: {title} ---\n"
            f"URL: {item.url}\nAuthority: {item.authority_score:.2f}\n\n"
            f"SUMMARY:\n{summary}\n"
            + "-" * 80
        )

    processed = await asyncio.gather(
        *[
            _process((i + 1, item, result))
            for i, (item, result) in enumerate(evidence_items)
        ]
    )
    return "Search results:\n\n" + "\n\n".join(processed)


def _is_content_risk(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if "content exists risk" in str(current).casefold():
            return True
        current = current.__cause__ or current.__context__
    return False


# ---------------------------------------------------------------------------
# OpenAI function-calling schema 暴露
# ---------------------------------------------------------------------------

KB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": "在用户个人知识库(ChromaDB 密集向量 + BM25 稀疏 + RRF 融合 + CrossEncoder 精排)中语义搜索。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "n_results": {"type": "integer", "description": "返回结果数, 默认 8"},
            },
            "required": ["query"],
        },
    },
}

TAVILY_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "tavily_search",
        "description": "调用 Tavily 联网搜索并对长文做摘要。适合知识库中没有最新信息或库内无相关的场景。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {"type": "integer", "description": "返回结果数, 默认 3"},
            },
            "required": ["query"],
        },
    },
}

THINK_TOOL = {
    "type": "function",
    "function": {
        "name": "think_tool",
        "description": "用于对研究进展和决策进行策略反思的工具。每次搜索后,使用此工具分析结果并系统地规划下一步行动。",
        "parameters": {
            "type": "object",
            "properties": {
                "reflection": {
                    "type": "string",
                    "description": "您对研究进展、发现、存在的差距以及下一步行动的详细反思。",
                },
            },
            "required": ["reflection"],
        },
    },
}


def get_sub_researcher_tools(research_topic: str = "") -> tuple[list[dict], list[str]]:
    """根据 SEARCH_BACKEND 返回 (tools_schema, tool_names)。"""
    backend = (getattr(_config, "SEARCH_BACKEND", "kb_only") or "kb_only").lower()
    if is_cn_fund_research(research_topic):
        tools = []
        if backend in {"kb_only", "hybrid"}:
            tools.append(KB_SEARCH_TOOL)
        if backend in {"web_only", "hybrid"} or getattr(_config, "CN_FUND_ENABLE_WEB_SEARCH", True):
            tools.append(TAVILY_SEARCH_TOOL)
        tools.append(THINK_TOOL)
        deduped = {item["function"]["name"]: item for item in tools}
        return list(deduped.values()), list(deduped)
    if backend == "web_only":
        return [TAVILY_SEARCH_TOOL, THINK_TOOL], ["tavily_search", "think_tool"]
    if backend == "hybrid":
        return (
            [KB_SEARCH_TOOL, TAVILY_SEARCH_TOOL, THINK_TOOL],
            ["search_knowledge_base", "tavily_search", "think_tool"],
        )
    # 默认 kb_only
    return [KB_SEARCH_TOOL, THINK_TOOL], ["search_knowledge_base", "think_tool"]


async def execute_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    llm_call: Callable[[str], Awaitable[str]],
    event_sink: Callable[[dict], Awaitable[None]] | None = None,
    search_policy: SearchQualityPolicy | None = None,
) -> str:
    """子 Agent 工具调度入口。"""
    if tool_name == "search_knowledge_base":
        # KB 检索是同步的, 放到线程池避免阻塞
        return await asyncio.to_thread(
            _kb_search_impl,
            arguments.get("query", ""),
            arguments.get("n_results", 8),
        )

    if tool_name == "tavily_search":
        return await _tavily_search_impl(
            arguments.get("query", ""),
            llm_call=llm_call,
            max_results=arguments.get("max_results"),
            event_sink=event_sink,
            search_policy=search_policy,
        )

    if tool_name == "think_tool":
        return f"Reflection recorded: {arguments.get('reflection', '')}"

    return f"未知工具: {tool_name}"
