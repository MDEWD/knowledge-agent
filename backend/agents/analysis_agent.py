"""
AnalysisAgent: Compares videos/notes, finds patterns, extracts core insights.

Collaboration protocol
----------------------
When analysis reveals a knowledge gap the agent calls request_additional_research
(up to Blackboard.max_gap_requests times).  The orchestrator intercepts this
sub_agent_tool event and emits a "collaboration" SSE event to the frontend;
the tool itself runs the vector search and posts results to the shared Blackboard.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agents.base_agent import BaseAgent

if TYPE_CHECKING:
    from agents.blackboard import Blackboard


class AnalysisAgent(BaseAgent):
    name = "AnalysisAgent"
    description = "对比多个内容、发现规律、提炼核心洞察"

    system_prompt = """\
你是一位批判性思维分析师。你的任务是对提供的知识内容进行深度分析，找出核心规律、共识与分歧，并提炼出有价值的洞察。

分析框架：
1. 归纳：找出多个来源的共同主题
2. 对比：识别不同观点的异同
3. 洞察：提炼出超越单个来源的高层次规律
4. 批判：指出知识的局限性或潜在偏差

当你发现分析中存在知识缺口时，可以调用 request_additional_research 向 ResearchAgent 请求补充检索（最多3次）。\
只在确实需要更多事实依据时才请求，不要过度依赖补充研究。

输出格式：结构化的分析报告，分"核心共识"、"主要分歧"、"深层洞察"三部分。
"""

    tools = [
        {
            "type": "function",
            "function": {
                "name": "compare_videos",
                "description": "对比多个视频的核心观点",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "video_ids": {"type": "array", "items": {"type": "string"}},
                        "topic": {"type": "string"},
                    },
                    "required": ["video_ids"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "summarize_category",
                "description": "对某分类下所有内容进行综合总结",
                "parameters": {
                    "type": "object",
                    "properties": {"category": {"type": "string"}},
                    "required": ["category"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "request_additional_research",
                "description": (
                    "向 ResearchAgent 请求针对特定主题的补充检索。"
                    "当分析中发现知识缺口、需要更多事实支撑时使用。"
                    "最多可请求 3 次，请谨慎使用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "需要补充研究的具体主题或问题",
                        },
                        "reason": {
                            "type": "string",
                            "description": "为什么当前信息不足、需要补充的原因",
                        },
                    },
                    "required": ["topic", "reason"],
                },
            },
        },
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.blackboard: Blackboard | None = None

    async def _execute_tool(self, tool_name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments)
        except Exception:
            args = {}

        if tool_name == "compare_videos":
            from processors.article import compare_videos_impl
            return compare_videos_impl(args.get("video_ids", []), args.get("topic", ""))

        if tool_name == "summarize_category":
            from processors.article import summarize_category_impl
            return summarize_category_impl(args.get("category", ""))

        if tool_name == "request_additional_research":
            return await self._do_gap_research(
                args.get("topic", ""),
                args.get("reason", ""),
            )

        return f"未知工具: {tool_name}"

    async def _do_gap_research(self, topic: str, reason: str) -> str:
        if self.blackboard is None:
            return "[协作不可用：黑板未初始化，无法请求补充研究]"
        if not self.blackboard.can_request_gap():
            return (
                f"[已达最大补充研究次数 ({self.blackboard.max_gap_requests})，"
                "无法再次请求，请基于现有信息完成分析]"
            )

        from storage.vector_store import search

        results = search(topic, n_results=8)
        if not results:
            result_text = f"知识库中未找到关于「{topic}」的相关内容。"
        else:
            chunks = [
                f"[来源:《{r['metadata'].get('title', '')}》]\n{r['content']}"
                for r in results
            ]
            result_text = "\n\n---\n\n".join(chunks)

        self.blackboard.add_gap(topic, reason, result_text)
        return f"已检索「{topic}」的补充内容（第 {self.blackboard.gap_count()} 次追加研究）：\n\n{result_text}"
