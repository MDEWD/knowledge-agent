"""
WritingAgent: Synthesizes research and analysis into structured reports.
"""
from __future__ import annotations

from agents.base_agent import BaseAgent


class WritingAgent(BaseAgent):
    name = "WritingAgent"
    description = "将研究与分析结果撰写成结构化报告"

    system_prompt = """\
你是一位专业的知识内容写作专家。你会接收到来自研究员和分析师的原始素材，将其整合成一篇高质量的综合报告。

写作要求：
1. 结构清晰：使用标题、小节、要点列表
2. 逻辑严密：观点之间有清晰的逻辑关联
3. 深度适中：既有概览性总结，也有关键细节
4. 语言精炼：避免冗余，每句话都有信息量
5. 实用导向：读者看完应有明确的收获或行动方向

报告结构：
## 执行摘要（3-5行）
## 核心发现
## 深度分析
## 关键洞察
## 行动建议（可选）
"""

    tools = []  # WritingAgent writes directly, no tools needed

    async def _execute_tool(self, tool_name: str, arguments: str) -> str:
        return ""
