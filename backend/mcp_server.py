#!/usr/bin/env python3
"""
MCP server — exposes the knowledge base as tools for Claude Desktop, Cursor, Windsurf, etc.

Run standalone:
    cd backend && python mcp_server.py

Claude Desktop config (~/.claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "knowledge-base": {
          "command": "/absolute/path/to/backend/.venv/bin/python",
          "args": ["/absolute/path/to/backend/mcp_server.py"],
          "env": { "DEEPSEEK_API_KEY": "your_key", "OBSIDIAN_VAULT": "/path/to/vault" }
        }
      }
    }
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make backend modules importable when run as a standalone script
sys.path.insert(0, str(Path(__file__).parent))

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from openai import AsyncOpenAI

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

server = Server("knowledge-base")

# ── Tool definitions ──────────────────────────────────────────────────────────

_TOOLS = [
    types.Tool(
        name="search_knowledge_base",
        description="在个人视频知识库中语义搜索，自动识别时间型/实体型/概念型查询走不同检索路径，返回带来源引用的相关内容片段",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词或自然语言问题"},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="get_video_note",
        description="获取某个视频的完整笔记，包含摘要、主要观点、关键概念、行动启示",
        inputSchema={
            "type": "object",
            "properties": {
                "video_id": {"type": "string", "description": "视频ID，可通过 list_videos_in_kb 获取"},
            },
            "required": ["video_id"],
        },
    ),
    types.Tool(
        name="list_videos_in_kb",
        description="列出知识库中所有视频和导入笔记，可按分类过滤",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "可选分类过滤：财经理财 / AI与科技 / 心理学 / 商业创业 / 健康生活 / 教育学习 / 历史文化 / 娱乐综艺 / 科学探索 / 其他",
                },
            },
        },
    ),
    types.Tool(
        name="summarize_category",
        description="对某个分类下的所有视频知识进行综合总结，提炼共同主题和核心洞察",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "分类名称"},
            },
            "required": ["category"],
        },
    ),
    types.Tool(
        name="compare_videos",
        description="对比多个视频的核心观点，找出共识、分歧和互补关系",
        inputSchema={
            "type": "object",
            "properties": {
                "video_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "视频ID列表（2-5个），可通过 list_videos_in_kb 获取",
                },
                "topic": {"type": "string", "description": "对比的主题或角度（可选）"},
            },
            "required": ["video_ids"],
        },
    ),
    types.Tool(
        name="search_youtube_videos",
        description="当知识库中没有相关内容时，在 YouTube 上搜索推荐视频",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索词"},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="generate_synthesis_article",
        description="基于知识库中的相关内容，生成一篇系统性综合文章并保存到 Obsidian",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "文章主题"},
            },
            "required": ["topic"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return _TOOLS


# ── Core search logic (mirrors _execute_tool in app.py, without SSE) ─────────

async def _search_kb(query: str) -> str:
    client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    from processors.rag_enhancer import (
        classify_intent, expand_queries, rewrite_query, rerank_with_significance,
    )
    from storage.vector_store import search, is_topic_covered
    from processors.significance import get_significance_map

    intent = await classify_intent(query, client, DEEPSEEK_MODEL)

    # Temporal: return recency-sorted list instead of semantic search
    if intent == "temporal":
        from storage.video_db import list_videos
        from storage.notes_db import list_notes
        items = sorted(
            [{"title": v["title"], "type": "视频", "created_at": v.get("created_at", ""), "url": v.get("url", "")} for v in list_videos()] +
            [{"title": n["title"], "type": "笔记", "created_at": n.get("imported_at", ""), "url": n.get("url", "")} for n in list_notes()],
            key=lambda x: x["created_at"],
            reverse=True,
        )[:10]
        if not items:
            return "知识库中暂无内容。"
        lines = [f"- [{i['type']}] 《{i['title']}》 {i['created_at'][:10] if i['created_at'] else ''}" for i in items]
        return "最近导入的内容：\n" + "\n".join(lines)

    # Multi-query expansion for conceptual queries
    query_variants = await expand_queries(query, client, DEEPSEEK_MODEL) if intent == "conceptual" else [query]
    primary_rewritten = await rewrite_query(query, client, DEEPSEEK_MODEL)
    all_queries = [primary_rewritten] + query_variants[1:]

    seen_keys: set[str] = set()
    all_candidates: list[dict] = []
    for q in all_queries:
        for c in search(q, 15):
            key = f"{c['metadata'].get('url', '')}::{c['metadata'].get('chunk_index', 0)}"
            if key not in seen_keys:
                seen_keys.add(key)
                all_candidates.append(c)

    if not all_candidates:
        return "知识库中没有相关内容。"

    sig_map = get_significance_map()
    results = rerank_with_significance(query, all_candidates, 6, sig_map)
    covered = is_topic_covered(query, 1, 1.0)

    source_map: dict[str, dict] = {}
    chunks: list[str] = []
    for r in results:
        meta = r["metadata"]
        url = meta.get("url", "")
        if url not in source_map:
            source_map[url] = {
                "index": len(source_map) + 1,
                "title": meta.get("title", ""),
                "url": url,
            }
        num = source_map[url]["index"]
        chunks.append(f"[来源{num}]《{meta.get('title', '')}》\n{r['content']}")

    text = "\n\n".join(chunks)
    if not covered:
        text = "【注意：知识库中暂无高度相关内容，以下为最近似结果】\n\n" + text

    sources = "\n".join(
        f"[来源{s['index']}] 《{s['title']}》 {s['url']}"
        for s in source_map.values()
    )
    return text + "\n\n---\n" + sources


# ── Tool call handler ─────────────────────────────────────────────────────────

def _text(content: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=content)]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "search_knowledge_base":
            return _text(await _search_kb(arguments.get("query", "")))

        if name == "get_video_note":
            from storage.video_db import get_video
            v = get_video(arguments.get("video_id", ""))
            if not v:
                return _text("未找到该视频")
            return _text(f"《{v['title']}》\n\n{v.get('insights', '暂无笔记')}")

        if name == "list_videos_in_kb":
            from storage.video_db import list_videos
            from storage.notes_db import list_notes
            category = arguments.get("category")
            videos = list_videos()
            notes = list_notes()
            if category:
                videos = [v for v in videos if v.get("category") == category]
                notes = [n for n in notes if n.get("category") == category]
            if not videos and not notes:
                return _text("知识库中没有任何内容" if not category else f"分类「{category}」下暂无内容")
            parts = []
            if videos:
                lines = [
                    f"- ID:{v['id']} 《{v['title']}》 [{v.get('category', '未知')}] {v.get('created_at', '')[:10]}"
                    for v in videos
                ]
                parts.append("【视频】\n" + "\n".join(lines))
            if notes:
                lines = [
                    f"- ID:{n['id']} 《{n['title']}》 [{n.get('category', '未知')}] {n.get('created_at', '')[:10]}"
                    for n in notes
                ]
                parts.append("【笔记】\n" + "\n".join(lines))
            return _text("\n\n".join(parts))

        if name == "summarize_category":
            from processors.article import summarize_category_impl
            return _text(summarize_category_impl(arguments.get("category", "")))

        if name == "compare_videos":
            from processors.article import compare_videos_impl
            return _text(compare_videos_impl(
                arguments.get("video_ids", []),
                arguments.get("topic", ""),
            ))

        if name == "search_youtube_videos":
            from extractors.youtube_search import search_youtube
            videos = search_youtube(arguments.get("query", ""), 5)
            if not videos:
                return _text("未找到相关视频")
            lines = [f"- 《{v['title']}》 {v['url']} 频道:{v['channel']}" for v in videos]
            return _text("\n".join(lines))

        if name == "generate_synthesis_article":
            from processors.article import generate_article
            result = generate_article(arguments.get("topic", ""))
            if result.get("error"):
                return _text(f"生成失败：{result['error']}")
            return _text(
                f"文章已生成并保存到 Obsidian（{result.get('source_count', 0)} 个来源）\n\n"
                f"{result.get('article', '')}"
            )

        return _text(f"未知工具：{name}")

    except Exception as e:
        return _text(f"工具执行出错：{e}")


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
