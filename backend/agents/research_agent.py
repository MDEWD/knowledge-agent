"""
ResearchAgent: Searches the knowledge base, retrieves video notes, lists content.
"""
from __future__ import annotations

import json
from agents.base_agent import BaseAgent


class ResearchAgent(BaseAgent):
    name = "ResearchAgent"
    description = "在知识库中检索信息、查找视频内容、发现知识关联"

    system_prompt = """\
你是一位严谨的知识库研究员。你的任务是在用户的个人知识库中检索相关信息，找出关键内容并整理成结构化的研究摘要。

工作原则：
- 先搜索再总结，不要凭空捏造内容
- 对检索结果进行批判性分析，标注信息来源
- 如果知识库中信息不足，明确说明
- 输出格式：先列出检索到的关键信息，再给出综合分析
"""

    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_knowledge_base",
                "description": "语义搜索知识库",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_videos_in_kb",
                "description": "列出知识库中所有视频和导入笔记",
                "parameters": {
                    "type": "object",
                    "properties": {"category": {"type": "string"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_video_note",
                "description": "获取某个视频的完整笔记",
                "parameters": {
                    "type": "object",
                    "properties": {"video_id": {"type": "string"}},
                    "required": ["video_id"],
                },
            },
        },
    ]

    async def _execute_tool(self, tool_name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments)
        except Exception:
            args = {}

        if tool_name == "search_knowledge_base":
            from storage.vector_store import search
            results = search(args.get("query", ""), n_results=8)
            if not results:
                return "知识库中未找到相关内容。"
            chunks = [
                f"[来源:《{r['metadata'].get('title', '')}》]\n{r['content']}"
                for r in results
            ]
            return "\n\n---\n\n".join(chunks)

        if tool_name == "list_videos_in_kb":
            from storage.video_db import list_videos
            from storage.notes_db import list_notes
            videos = list_videos()
            notes = list_notes()
            lines = [f"[视频] {v['title']} (ID:{v['id']}, 分类:{v.get('category','未知')})" for v in videos]
            lines += [f"[笔记] {n['title']} (ID:{n['id']}, 类型:{n.get('file_type','')})" for n in notes]
            return "\n".join(lines) if lines else "知识库为空"

        if tool_name == "get_video_note":
            from storage.video_db import get_video
            v = get_video(args.get("video_id", ""))
            if not v:
                return "未找到该视频"
            return f"《{v['title']}》\n\n{v.get('insights', '暂无笔记')}"

        return f"未知工具: {tool_name}"
