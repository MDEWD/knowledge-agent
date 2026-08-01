"""
DeepResearch 融合模块: 在 knowledge-agent 内复刻 DeepResearch 项目的
「自进化 + 对抗降噪」循环(简报 → 初稿 → supervisor think/conduct/refine →
red_team → evaluator 评分 → final_report), 并适配 AsyncOpenAI(DeepSeek)。

数据源由 config.SEARCH_BACKEND 决定:
  - kb_only  : 仅检索个人知识库 (ChromaDB + BM25 + CrossEncoder)
  - web_only : 仅 Tavily 联网搜索
  - hybrid   : 两者并行融合
"""
from .orchestrator import DeepResearchOrchestrator

__all__ = ["DeepResearchOrchestrator"]
