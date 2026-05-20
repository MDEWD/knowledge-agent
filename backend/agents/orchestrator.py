"""
OrchestratorAgent: Plans, dispatches to sub-agents in parallel, then synthesizes.

Flow:
  1. plan(task) → decompose into subtasks for ResearchAgent + AnalysisAgent
  2. asyncio.gather → run both sub-agents concurrently
     Each sub-agent uses CompletionEvaluator to decide when it has enough.
  3. WritingAgent → synthesize results into final streaming report
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from openai import AsyncOpenAI

from agents.base_agent import BaseAgent
from agents.completion_evaluator import CompletionEvaluator
from agents.research_agent import ResearchAgent
from agents.analysis_agent import AnalysisAgent
from agents.writing_agent import WritingAgent

_PLANNER_PROMPT = """\
你是一个任务规划专家。根据用户的复杂任务，将其分解为两个并行子任务：
- research_task: 给 ResearchAgent 的检索任务（在知识库中搜索什么）
- analysis_task: 给 AnalysisAgent 的分析任务（分析/对比什么角度）

以 JSON 格式返回（不要有任何其他内容）：
{
  "research_task": "...",
  "analysis_task": "..."
}
"""


class OrchestratorAgent:
    """
    Parallel orchestrator: Research + Analysis run concurrently,
    each with an independent CompletionEvaluator, then WritingAgent
    synthesizes the combined results.
    """

    def __init__(self, client: AsyncOpenAI, model: str):
        self.client = client
        self.model = model

        # One shared evaluator instance per sub-agent type is fine — they
        # are stateless and use only the EvalContext passed at call time.
        evaluator = CompletionEvaluator(
            client,
            model,
            confidence_threshold=0.7,
            skip_first_steps=1,
        )

        self.research = ResearchAgent(client, model, evaluator=evaluator)
        self.analysis = AnalysisAgent(client, model, evaluator=evaluator)
        self.writer = WritingAgent(client, model)

    async def _plan(self, task: str) -> dict:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _PLANNER_PROMPT},
                {"role": "user", "content": f"用户任务：{task}"},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(resp.choices[0].message.content)
        except Exception:
            return {
                "research_task": f"搜索和整理与以下主题相关的所有知识库内容：{task}",
                "analysis_task": f"分析知识库中与以下主题相关内容的核心观点和规律：{task}",
            }

    async def run_stream(self, task: str) -> AsyncGenerator[dict, None]:
        """
        Stream orchestration events:
          plan → agent_start (×2) → agent_done (×2, with stop_reason)
               → agent_start (writing) → text chunks → done
        """
        # ── Phase 1: Plan ──────────────────────────────────────────────────────
        plan = await self._plan(task)
        research_task = plan.get("research_task", task)
        analysis_task = plan.get("analysis_task", task)

        yield {
            "type": "plan",
            "steps": [
                {"agent": "ResearchAgent", "task": research_task, "status": "pending"},
                {"agent": "AnalysisAgent", "task": analysis_task, "status": "pending"},
                {"agent": "WritingAgent", "task": "综合以上结果，撰写深度报告", "status": "pending"},
            ],
        }

        # ── Phase 2: Parallel execution ────────────────────────────────────────
        yield {"type": "agent_start", "agent": "ResearchAgent", "task": research_task}
        yield {"type": "agent_start", "agent": "AnalysisAgent", "task": analysis_task}

        (research_result, research_decision), (analysis_result, analysis_decision) = \
            await asyncio.gather(
                self.research.run(research_task),
                self.analysis.run(analysis_task),
            )

        yield {
            "type": "agent_done",
            "agent": "ResearchAgent",
            "summary": research_result[:300] + ("…" if len(research_result) > 300 else ""),
            "stop_reason": research_decision.reason if research_decision else "自然结束",
        }
        yield {
            "type": "agent_done",
            "agent": "AnalysisAgent",
            "summary": analysis_result[:300] + ("…" if len(analysis_result) > 300 else ""),
            "stop_reason": analysis_decision.reason if analysis_decision else "自然结束",
        }

        # ── Phase 3: Writing (streaming) ───────────────────────────────────────
        writing_task = (
            f"原始任务：{task}\n\n"
            f"=== 研究员报告 ===\n{research_result}\n\n"
            f"=== 分析师报告 ===\n{analysis_result}\n\n"
            "请基于以上素材，撰写一份深度综合报告。"
        )

        yield {"type": "agent_start", "agent": "WritingAgent", "task": "综合研究与分析结果，撰写报告"}

        messages = [
            {"role": "system", "content": self.writer.system_prompt},
            {"role": "user", "content": writing_task},
        ]
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.5,
            stream=True,
        )
        full_text = ""
        async for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                full_text += delta
                yield {"type": "text", "content": delta}

        yield {
            "type": "agent_done",
            "agent": "WritingAgent",
            "summary": full_text[:300] + ("…" if len(full_text) > 300 else ""),
            "stop_reason": "报告撰写完成",
        }
        yield {"type": "done"}
