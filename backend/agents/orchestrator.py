"""
OrchestratorAgent: Plans, dispatches sub-agents sequentially with inter-agent
collaboration via a shared Blackboard, then synthesises with WritingAgent.

Flow
----
  1. plan(task) → decompose into research_task + analysis_task
  2. HITL gate (optional): yield hitl_confirm, wait for human approval
  3. Phase 2a — ResearchAgent runs; result posted to Blackboard
  4. Phase 2b — AnalysisAgent runs with Blackboard context injected.
       If AnalysisAgent calls request_additional_research(topic, reason):
         • a "collaboration" SSE event is emitted to the frontend
         • the tool executes a targeted vector search and posts results back
           to the Blackboard so the context stays current
  5. WritingAgent → synthesises both results into a final streaming report

Collaboration protocol
----------------------
The Blackboard is the shared state bus:
  - ResearchAgent posts its full result via blackboard.post_finding()
  - AnalysisAgent reads blackboard.get_research_context() as a context prefix
  - When AnalysisAgent calls request_additional_research, the Orchestrator
    intercepts the sub_agent_tool event (tool == "request_additional_research"),
    emits a {"type": "collaboration", ...} event to the frontend, and also
    forwards the original event so the tool-chip still appears in the UI.
    AnalysisAgent._execute_tool handles the actual search and Blackboard write.

Checkpoint resume (three steps)
---------------------------------
  step=1 → ResearchAgent done; resume skips to AnalysisAgent with saved result
  step=2 → Both sub-agents done; skip straight to WritingAgent

HITL (Human-in-the-Loop)
-------------------------
When confirm_event is supplied, the orchestrator yields a hitl_confirm event
after planning and then awaits the event (max 120 s).
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING, AsyncGenerator

from openai import AsyncOpenAI

from agents.base_agent import BaseAgent
from agents.blackboard import Blackboard
from agents.completion_evaluator import CompletionEvaluator
from agents.research_agent import ResearchAgent
from agents.analysis_agent import AnalysisAgent
from agents.writing_agent import WritingAgent
from harness.retry import CircuitBreaker, RetryPolicy

if TYPE_CHECKING:
    from harness.checkpoint import CheckpointStore

_PLANNER_PROMPT = """\
你是一个任务规划专家。根据用户的复杂任务，将其分解为两个子任务：
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
    Sequential collaborative orchestrator:
      ResearchAgent → Blackboard → AnalysisAgent (with gap-fill) → WritingAgent
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
    # Main entry point
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        task: str,
        *,
        run_id: str | None = None,
        confirm_event: asyncio.Event | None = None,
        lesson_context: str = "",
    ) -> AsyncGenerator[dict, None]:
        """
        Stream orchestration events:
          plan → [hitl_confirm → await confirmation] →
          agent_start(Research) → sub_agent_tool events → agent_done(Research) →
          agent_start(Analysis) → sub_agent_tool/collaboration events → agent_done(Analysis) →
          agent_start(Writing) → text chunks → agent_done(Writing) → done
        """
        run_id = run_id or str(uuid.uuid4())
        # Prepend harness lessons to task so all sub-agents benefit
        enriched_task = f"{lesson_context}\n\n{task}".strip() if lesson_context else task

        # ── Try to resume ──────────────────────────────────────────────────────
        saved = self._load_checkpoint(run_id)
        resuming_from_step = int(saved.get("step", 0)) if saved else 0

        # ── Phase 1: Plan ──────────────────────────────────────────────────────
        plan = await self._plan(enriched_task)
        research_task = plan.get("research_task", enriched_task)
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

        # ── Phase 2: Sequential collaborative execution ────────────────────────
        blackboard = Blackboard()
        research_result = ""
        analysis_result = ""

        if resuming_from_step >= 2 and saved:
            # Both agents done — restore and fast-forward to WritingAgent
            research_result = saved.get("research_result", "")
            analysis_result = saved.get("analysis_result", "")

            yield {
                "type": "agent_done", "agent": "ResearchAgent",
                "summary": research_result[:300] + ("…" if len(research_result) > 300 else ""),
                "stop_reason": saved.get("research_stop_reason", "已从断点恢复"),
            }
            yield {
                "type": "agent_done", "agent": "AnalysisAgent",
                "summary": analysis_result[:300] + ("…" if len(analysis_result) > 300 else ""),
                "stop_reason": saved.get("analysis_stop_reason", "已从断点恢复"),
            }

        else:
            # ── Phase 2a: ResearchAgent ────────────────────────────────────────
            yield {"type": "agent_start", "agent": "ResearchAgent", "task": research_task}

            if resuming_from_step >= 1 and saved:
                # Research done, resume from analysis
                research_result = saved.get("research_result", "")
                blackboard.post_finding("ResearchAgent", research_task, research_result)
                yield {
                    "type": "agent_done", "agent": "ResearchAgent",
                    "summary": research_result[:300] + ("…" if len(research_result) > 300 else ""),
                    "stop_reason": saved.get("research_stop_reason", "已从断点恢复"),
                }
            else:
                async for event in self.research.run_stream(research_task):
                    if event["type"] == "sub_agent_done":
                        research_result = event["result"]
                        blackboard.post_finding("ResearchAgent", research_task, research_result)
                        yield {
                            "type": "agent_done", "agent": "ResearchAgent",
                            "summary": research_result[:300] + ("…" if len(research_result) > 300 else ""),
                            "stop_reason": event.get("stop_reason") or "自然结束",
                            "usage": event.get("usage"),
                        }
                    else:
                        yield event

                # Checkpoint after Research so a crash before Analysis can resume
                self._save_checkpoint(run_id, task, step=1, metadata={
                    "step": 1,
                    "research_task": research_task,
                    "analysis_task": analysis_task,
                    "research_result": research_result,
                    "research_stop_reason": "",
                })

            # ── Phase 2b: AnalysisAgent with Blackboard context ────────────────
            self.analysis.blackboard = blackboard
            analysis_context = blackboard.get_research_context()

            yield {"type": "agent_start", "agent": "AnalysisAgent", "task": analysis_task}

            async for event in self.analysis.run_stream(analysis_task, context=analysis_context):
                if event["type"] == "sub_agent_done":
                    analysis_result = event["result"]
                    yield {
                        "type": "agent_done", "agent": "AnalysisAgent",
                        "summary": analysis_result[:300] + ("…" if len(analysis_result) > 300 else ""),
                        "stop_reason": event.get("stop_reason") or "自然结束",
                        "usage": event.get("usage"),
                    }

                elif (event["type"] == "sub_agent_tool"
                      and event.get("tool") == "request_additional_research"):
                    # Emit collaboration event so the frontend shows the connector
                    try:
                        collab_args = json.loads(event.get("args", "{}"))
                    except Exception:
                        collab_args = {}
                    yield {
                        "type": "collaboration",
                        "from_agent": "AnalysisAgent",
                        "to_agent": "ResearchAgent",
                        "topic": collab_args.get("topic", ""),
                        "reason": collab_args.get("reason", ""),
                    }
                    # Also forward the raw event so the tool chip still renders
                    yield event

                else:
                    yield event

            # Checkpoint after both sub-agents complete
            self._save_checkpoint(run_id, task, step=2, metadata={
                "step": 2,
                "research_result": research_result,
                "research_stop_reason": "",
                "analysis_result": analysis_result,
                "analysis_stop_reason": "",
                "blackboard": blackboard.to_dict(),
            })

        # ── Phase 3: WritingAgent (streaming synthesis) ────────────────────────
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
            stream_options={"include_usage": True},
        )
        full_text = ""
        writing_input_tokens = 0
        writing_output_tokens = 0
        async for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                full_text += delta
                yield {"type": "text", "content": delta}
            if chunk.usage:
                writing_input_tokens = chunk.usage.prompt_tokens or 0
                writing_output_tokens = chunk.usage.completion_tokens or 0

        yield {
            "type": "agent_done",
            "agent": "WritingAgent",
            "summary": full_text[:300] + ("…" if len(full_text) > 300 else ""),
            "stop_reason": "报告撰写完成",
            "usage": {"input_tokens": writing_input_tokens, "output_tokens": writing_output_tokens, "tool_calls": 0},
        }

        self._delete_checkpoint(run_id)
        yield {"type": "done"}
