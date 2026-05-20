"""
OrchestratorAgent: Plans, dispatches to sub-agents in parallel, then synthesizes.

Flow:
  1. plan(task) → decompose into subtasks for ResearchAgent + AnalysisAgent
  2. HITL gate (optional): yield hitl_confirm, wait for human approval
  3. Queue-based parallel streaming → run both sub-agents concurrently,
     forwarding their sub_agent_tool events in real time as they arrive.
     Each sub-agent uses CompletionEvaluator to decide when it has enough.
  4. WritingAgent → synthesize results into final streaming report

Checkpoint resume
-----------------
If a CheckpointStore is supplied and a prior run exists for run_id:
  - step=2 in the checkpoint → both sub-agents done; skip to WritingAgent.

HITL (Human-in-the-Loop)
-------------------------
When confirm_event is supplied, the orchestrator yields a hitl_confirm event
after planning and then awaits the event (max 120 s).  The caller (app.py)
stores the event keyed by run_id and sets it when the user confirms via
POST /api/agent/confirm/{run_id}.
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

    # ------------------------------------------------------------------
    # Planner
    # ------------------------------------------------------------------

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

    def _save_checkpoint(self, run_id: str, task: str, step: int, metadata: dict) -> None:
        if self.checkpoint_store is None:
            return
        from harness.checkpoint import Checkpoint
        cp = Checkpoint(run_id=run_id, task=task, step=step, history=[], metadata=metadata)
        self.checkpoint_store.save(cp)

    def _delete_checkpoint(self, run_id: str) -> None:
        if self.checkpoint_store is not None:
            self.checkpoint_store.delete(run_id)

    def _load_checkpoint(self, run_id: str) -> dict | None:
        if self.checkpoint_store is None:
            return None
        cp = self.checkpoint_store.load(run_id)
        return cp.metadata if cp else None

    # ------------------------------------------------------------------
    # Queue-based parallel streaming
    # ------------------------------------------------------------------

    async def _stream_parallel(
        self,
        research_task: str,
        analysis_task: str,
        results_out: dict,
    ) -> AsyncGenerator[dict, None]:
        """
        Run ResearchAgent and AnalysisAgent concurrently, yielding events in
        arrival order.  Results are written to results_out when each agent
        finishes (keyed by agent name).
        """
        queue: asyncio.Queue = asyncio.Queue()

        async def _drain(agent, agent_task):
            try:
                async for event in agent.run_stream(agent_task):
                    await queue.put(event)
                    if event["type"] == "sub_agent_done":
                        results_out[agent.name] = {
                            "result": event["result"],
                            "stop_reason": event.get("stop_reason"),
                        }
            except Exception as exc:
                # Surface error without crashing the orchestrator
                results_out[agent.name] = {
                    "result": f"[{agent.name} 执行出错: {exc}]",
                    "stop_reason": str(exc),
                }
                await queue.put({
                    "type": "sub_agent_done",
                    "agent": agent.name,
                    "result": results_out[agent.name]["result"],
                    "stop_reason": str(exc),
                })
            finally:
                await queue.put({"type": "_sentinel"})

        t1 = asyncio.create_task(_drain(self.research, research_task))
        t2 = asyncio.create_task(_drain(self.analysis, analysis_task))

        pending = 2
        while pending > 0:
            event = await queue.get()
            if event["type"] == "_sentinel":
                pending -= 1
            elif event["type"] == "sub_agent_done":
                # Convert to public agent_done event for the frontend
                yield {
                    "type": "agent_done",
                    "agent": event["agent"],
                    "summary": event["result"][:300] + ("…" if len(event["result"]) > 300 else ""),
                    "stop_reason": event.get("stop_reason") or "自然结束",
                }
            else:
                # Forward sub_agent_tool events (and any others) transparently
                yield event

        await asyncio.gather(t1, t2, return_exceptions=True)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        task: str,
        *,
        run_id: str | None = None,
        confirm_event: asyncio.Event | None = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream orchestration events:
          plan → [hitl_confirm → await confirmation] →
          agent_start (×2) + sub_agent_tool events → agent_done (×2) →
          agent_start (writing) → text chunks → done
        """
        run_id = run_id or str(uuid.uuid4())

        # ── Try to resume ──────────────────────────────────────────────────────
        saved = self._load_checkpoint(run_id)
        resuming_from_step = int(saved.get("step", 0)) if saved else 0

        # ── Phase 1: Plan ──────────────────────────────────────────────────────
        plan = await self._plan(task)
        research_task = plan.get("research_task", task)
        analysis_task = plan.get("analysis_task", task)

        plan_steps = [
            {"agent": "ResearchAgent", "task": research_task, "status": "pending"},
            {"agent": "AnalysisAgent", "task": analysis_task, "status": "pending"},
            {"agent": "WritingAgent", "task": "综合以上结果，撰写深度报告", "status": "pending"},
        ]
        yield {"type": "plan", "steps": plan_steps}

        # ── HITL gate ──────────────────────────────────────────────────────────
        if confirm_event is not None:
            yield {
                "type": "hitl_confirm",
                "run_id": run_id,
                "steps": plan_steps,
            }
            try:
                await asyncio.wait_for(confirm_event.wait(), timeout=120.0)
            except asyncio.TimeoutError:
                yield {
                    "type": "error",
                    "message": "等待确认超时（120 秒），任务已取消。",
                }
                return

        # ── Phase 2: Parallel execution ────────────────────────────────────────
        if resuming_from_step >= 2 and saved:
            research_result = saved.get("research_result", "")
            analysis_result = saved.get("analysis_result", "")

            yield {"type": "agent_done", "agent": "ResearchAgent",
                   "summary": research_result[:300] + ("…" if len(research_result) > 300 else ""),
                   "stop_reason": saved.get("research_stop_reason", "已从断点恢复")}
            yield {"type": "agent_done", "agent": "AnalysisAgent",
                   "summary": analysis_result[:300] + ("…" if len(analysis_result) > 300 else ""),
                   "stop_reason": saved.get("analysis_stop_reason", "已从断点恢复")}
        else:
            yield {"type": "agent_start", "agent": "ResearchAgent", "task": research_task}
            yield {"type": "agent_start", "agent": "AnalysisAgent", "task": analysis_task}

            results: dict = {}
            async for event in self._stream_parallel(research_task, analysis_task, results):
                yield event

            research_result = results.get("ResearchAgent", {}).get("result", "")
            analysis_result = results.get("AnalysisAgent", {}).get("result", "")

            self._save_checkpoint(run_id, task, step=2, metadata={
                "step": 2,
                "research_result": research_result,
                "research_stop_reason": results.get("ResearchAgent", {}).get("stop_reason", ""),
                "analysis_result": analysis_result,
                "analysis_stop_reason": results.get("AnalysisAgent", {}).get("stop_reason", ""),
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

        self._delete_checkpoint(run_id)
        yield {"type": "done"}
