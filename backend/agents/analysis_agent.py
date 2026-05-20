"""
AnalysisAgent: Compares videos/notes, finds patterns, extracts core insights.
"""
from __future__ import annotations

import json
from agents.base_agent import BaseAgent


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
    ]

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

        return f"未知工具: {tool_name}"
