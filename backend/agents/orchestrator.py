"""
OrchestratorAgent: Plans, dispatches to sub-agents in parallel, then synthesizes.

Flow:
  1. plan(task) → decompose into subtasks for ResearchAgent + AnalysisAgent
  2. asyncio.gather → run both sub-agents concurrently
     Each sub-agent uses CompletionEvaluator to decide when it has enough.
  3. WritingAgent → synthesize results into final streaming report

Checkpoint resume
-----------------
If a CheckpointStore is supplied and a prior run exists for run_id:
  - step=1 in the checkpoint → research already done; skip Phase 2 research only.
  - step=2               → both research and analysis done; jump straight to writing.
This means a crash mid-run is resumable without re-running expensive LLM sub-agents.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING, AsyncGenerator

from openai import AsyncOpenAI

from agents.base_agent import BaseAgent
from agents.completion_evaluator import CompletionEvaluator
from agents.research_agent import ResearchAgent
from agents.analysis_agent import AnalysisAgent
from agents.writing_agent import WritingAgent
from harness.retry import CircuitBreaker, RetryPolicy

if TYPE_CHECKING:
    from harness.checkpoint import CheckpointStore

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

    Parameters
    ----------
    client           AsyncOpenAI-compatible client.
    model            Model to use for all agents.
    checkpoint_store Optional CheckpointStore; when supplied the orchestrator
                     saves a snapshot after each completed sub-agent phase so
                     the run can be resumed after a crash.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        *,
        checkpoint_store: "CheckpointStore | None" = None,
        policy: RetryPolicy | None = None,
        circuit: CircuitBreaker | None = None,
    ):
        self.client = client
        self.model = model
        self.checkpoint_store = checkpoint_store
        self._policy = policy
        self._circuit = circuit

        evaluator = CompletionEvaluator(
            client,
            model,
            confidence_threshold=0.7,
            skip_first_steps=1,
        )

        self.research = ResearchAgent(client, model, evaluator=evaluator,
                                      policy=policy, circuit=circuit)
        self.analysis = AnalysisAgent(client, model, evaluator=evaluator,
                                      policy=policy, circuit=circuit)
        self.writer = WritingAgent(client, model,
                                   policy=policy, circuit=circuit)

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

    # ------------------------------------------------------------------
    # Checkpoint helpers
    # ------------------------------------------------------------------

    def _save_checkpoint(
        self,
        run_id: str,
        task: str,
        step: int,
        metadata: dict,
    ) -> None:
        """Persist run state; no-op when no checkpoint_store is configured."""
        if self.checkpoint_store is None:
            return
        from harness.checkpoint import Checkpoint
        cp = Checkpoint(
            run_id=run_id,
            task=task,
            step=step,
            history=[],      # orchestrator doesn't use message history
            metadata=metadata,
        )
        self.checkpoint_store.save(cp)

    def _delete_checkpoint(self, run_id: str) -> None:
        if self.checkpoint_store is not None:
            self.checkpoint_store.delete(run_id)

    def _load_checkpoint(self, run_id: str) -> "dict | None":
        """Return checkpoint metadata dict, or None if nothing saved."""
        if self.checkpoint_store is None:
            return None
        cp = self.checkpoint_store.load(run_id)
        return cp.metadata if cp else None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        task: str,
        *,
        run_id: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream orchestration events:
          plan → agent_start (×2) → agent_done (×2, with stop_reason)
               → agent_start (writing) → text chunks → done

        If run_id is provided and a checkpoint exists, completed phases are
        skipped and previously-saved results are used directly.
        """
        run_id = run_id or str(uuid.uuid4())

        # ── Try to resume from checkpoint ─────────────────────────────────────
        saved = self._load_checkpoint(run_id)
        resuming_from_step = int(saved.get("step", 0)) if saved else 0

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
        if resuming_from_step >= 2 and saved:
            # Both sub-agents already completed — use saved results
            research_result = saved.get("research_result", "")
            analysis_result = saved.get("analysis_result", "")
            research_decision_reason = saved.get("research_stop_reason", "已从断点恢复")
            analysis_decision_reason = saved.get("analysis_stop_reason", "已从断点恢复")

            yield {"type": "agent_done", "agent": "ResearchAgent",
                   "summary": research_result[:300] + ("…" if len(research_result) > 300 else ""),
                   "stop_reason": research_decision_reason}
            yield {"type": "agent_done", "agent": "AnalysisAgent",
                   "summary": analysis_result[:300] + ("…" if len(analysis_result) > 300 else ""),
                   "stop_reason": analysis_decision_reason}

        elif resuming_from_step == 1 and saved:
            # Research done; only re-run analysis
            research_result = saved.get("research_result", "")
            research_decision_reason = saved.get("research_stop_reason", "已从断点恢复")

            yield {"type": "agent_done", "agent": "ResearchAgent",
                   "summary": research_result[:300] + ("…" if len(research_result) > 300 else ""),
                   "stop_reason": research_decision_reason}
            yield {"type": "agent_start", "agent": "AnalysisAgent", "task": analysis_task}

            analysis_result, analysis_decision = await self.analysis.run(analysis_task)
            analysis_decision_reason = analysis_decision.reason if analysis_decision else "自然结束"

            yield {"type": "agent_done", "agent": "AnalysisAgent",
                   "summary": analysis_result[:300] + ("…" if len(analysis_result) > 300 else ""),
                   "stop_reason": analysis_decision_reason}

            self._save_checkpoint(run_id, task, step=2, metadata={
                "step": 2,
                "research_result": research_result,
                "research_stop_reason": research_decision_reason,
                "analysis_result": analysis_result,
                "analysis_stop_reason": analysis_decision_reason,
            })

        else:
            # Fresh run — execute both sub-agents in parallel
            yield {"type": "agent_start", "agent": "ResearchAgent", "task": research_task}
            yield {"type": "agent_start", "agent": "AnalysisAgent", "task": analysis_task}

            (research_result, research_decision), (analysis_result, analysis_decision) = \
                await asyncio.gather(
                    self.research.run(research_task),
                    self.analysis.run(analysis_task),
                )

            research_decision_reason = research_decision.reason if research_decision else "自然结束"
            analysis_decision_reason = analysis_decision.reason if analysis_decision else "自然结束"

            yield {"type": "agent_done", "agent": "ResearchAgent",
                   "summary": research_result[:300] + ("…" if len(research_result) > 300 else ""),
                   "stop_reason": research_decision_reason}
            yield {"type": "agent_done", "agent": "AnalysisAgent",
                   "summary": analysis_result[:300] + ("…" if len(analysis_result) > 300 else ""),
                   "stop_reason": analysis_decision_reason}

            # Save full checkpoint so a crash before writing can resume here
            self._save_checkpoint(run_id, task, step=2, metadata={
                "step": 2,
                "research_result": research_result,
                "research_stop_reason": research_decision_reason,
                "analysis_result": analysis_result,
                "analysis_stop_reason": analysis_decision_reason,
            })

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

        # Clean up checkpoint now that the full run succeeded
        self._delete_checkpoint(run_id)

        yield {"type": "done"}
