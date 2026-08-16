"""LangGraph runtime for durable, typed DeepResearch execution."""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from agents.deep_research.budget import ResearchBudgetExceeded
from agents.deep_research.citation_validator import CitationValidator, ensure_clickable_sources
from agents.deep_research.search_policy import SearchQualityPolicy
from agents.deep_research.state import (
    ResearchPhase,
    ResearchState,
    ResearchStatus,
)
from agents.deep_research.stop_policy import StopPolicy
from evals.deep_research_eval import evaluate_research_run

if TYPE_CHECKING:
    from agents.deep_research.orchestrator import DeepResearchOrchestrator

logger = logging.getLogger(__name__)

_LEGACY_CHECKPOINT_TYPES = (
    ("agents.deep_research.state", "ResearchPhase"),
    ("agents.deep_research.state", "ResearchStatus"),
)


class _DeepResearchSqliteSaver(AsyncSqliteSaver):
    """SQLite saver restricted to the two enum types used by legacy checkpoints."""

    def __init__(self, conn) -> None:
        super().__init__(
            conn,
            serde=JsonPlusSerializer(
                allowed_msgpack_modules=_LEGACY_CHECKPOINT_TYPES,
            ),
        )


class DeepResearchGraphRuntime:
    """Deep Module exposing start/resume through one streaming interface."""

    def __init__(
        self,
        orchestrator: "DeepResearchOrchestrator",
        *,
        checkpoint_path: str | Path,
        stop_policy: StopPolicy | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.checkpoint_path = Path(checkpoint_path)
        self.stop_policy = stop_policy or StopPolicy()
        self.cancel_event = cancel_event or asyncio.Event()

    def _build(self, checkpointer: AsyncSqliteSaver):
        orchestrator = self.orchestrator
        cancel_event = self.cancel_event
        stop_policy = self.stop_policy

        async def brief_node(state: ResearchState) -> dict:
            emit = get_stream_writer()
            if cancel_event.is_set():
                return _cancelled_update()
            emit({
                "type": "plan",
                "steps": [
                    {"agent": "BriefWriter", "task": "生成研究简报", "status": "pending"},
                    {"agent": "DraftWriter", "task": "生成报告初稿", "status": "pending"},
                    {"agent": "Supervisor", "task": "证据驱动的多步研究循环", "status": "pending"},
                    {"agent": "FinalWriter", "task": "生成并校验最终报告", "status": "pending"},
                ],
            })
            emit({"type": "agent_start", "agent": "BriefWriter", "task": "生成研究简报"})
            brief = await orchestrator._write_brief(state.task)
            emit({"type": "research_brief", "content": brief})
            emit({
                "type": "agent_done",
                "agent": "BriefWriter",
                "summary": brief[:300] + ("…" if len(brief) > 300 else ""),
                "stop_reason": "简报生成完成",
            })
            return {
                "brief": brief,
                "phase": ResearchPhase.PLANNING.value,
                "status": ResearchStatus.RUNNING.value,
                "usage": orchestrator.budget.usage.model_dump(mode="json"),
            }

        async def draft_node(state: ResearchState) -> dict:
            emit = get_stream_writer()
            if cancel_event.is_set():
                return _cancelled_update()
            emit({"type": "agent_start", "agent": "DraftWriter", "task": "基于简报撰写报告初稿"})
            draft = await orchestrator._write_draft(state.brief)
            emit({"type": "draft_update", "content": draft, "iteration": 0, "avg_score": None})
            emit({
                "type": "agent_done",
                "agent": "DraftWriter",
                "summary": draft[:300] + ("…" if len(draft) > 300 else ""),
                "stop_reason": "初稿生成完成",
            })
            emit({
                "type": "agent_start",
                "agent": "Supervisor",
                "task": "执行证据检索、对抗审查和自适应停止",
            })
            return {
                "draft": draft,
                "phase": ResearchPhase.RESEARCHING.value,
                "usage": orchestrator.budget.usage.model_dump(mode="json"),
            }

        async def supervisor_node(state: ResearchState) -> dict:
            emit = get_stream_writer()
            if cancel_event.is_set():
                return _cancelled_update()

            # Rehydrate run-scoped search memory when this node is resumed in a
            # new process, so checkpoint recovery cannot repeat paid queries or
            # re-emit URLs that were already accepted before the interruption.
            search_policy = getattr(orchestrator, "_search_policy", None)
            if search_policy is None:
                search_policy = SearchQualityPolicy()
                orchestrator._search_policy = search_policy
            search_policy.seen_queries.update(state.query_history)
            search_policy.seen_urls.update(
                item.url for item in state.evidence if item.url
            )

            final_state = state
            try:
                async for event in orchestrator._run_supervisor_loop(
                    task=state.task,
                    brief=state.brief,
                    draft=state.draft,
                    run_id=state.run_id,
                    research_state=state,
                    single_iteration=True,
                ):
                    if event.get("type") == "__supervisor_final__":
                        final_state = event["state"]
                    else:
                        emit(event)
            except ResearchBudgetExceeded as exc:
                final_state.status = ResearchStatus.BUDGET_EXCEEDED
                final_state.stop_reason = str(exc)

            provider_degraded = final_state.stop_reason.startswith("provider_unavailable:")
            decision = stop_policy.evaluate(final_state, orchestrator.budget)
            requested = final_state.supervisor_requested_complete
            can_honor_request = (
                requested
                and not final_state.has_open_high_critique
                and bool(final_state.evidence)
                and bool(final_state.evaluations)
            )
            if provider_degraded or decision.should_stop or can_honor_request:
                final_state.phase = ResearchPhase.FINALIZING
                final_state.stop_reason = (
                    final_state.stop_reason
                    if provider_degraded
                    else decision.detail
                    if decision.should_stop
                    else "Supervisor completed after quality gates"
                )
                emit({
                    "type": "stop_decision",
                    "reason": (
                        "provider_degraded"
                        if provider_degraded
                        else decision.reason.value
                        if decision.should_stop
                        else "supervisor_complete"
                    ),
                    "detail": final_state.stop_reason,
                    "forced": decision.forced or provider_degraded,
                })
                emit({
                    "type": "agent_done",
                    "agent": "Supervisor",
                    "summary": final_state.draft[:300],
                    "stop_reason": final_state.stop_reason,
                })
            else:
                final_state.supervisor_requested_complete = False
                emit({
                    "type": "stop_decision",
                    "reason": decision.reason.value,
                    "detail": decision.detail,
                    "forced": False,
                })
            final_state.usage = orchestrator.budget.usage
            final_state.query_history = sorted(search_policy.seen_queries)
            return final_state.to_checkpoint()

        def route_after_supervisor(state: ResearchState) -> str:
            if state.status in {
                ResearchStatus.CANCELLED,
                ResearchStatus.FAILED,
            }:
                return END
            if state.phase is ResearchPhase.FINALIZING:
                return "final"
            return "supervisor"

        async def final_node(state: ResearchState) -> dict:
            emit = get_stream_writer()
            if cancel_event.is_set():
                return _cancelled_update()
            emit({"type": "phase_status", "phase": "finalizing", "label": "正在生成并校验最终研究报告"})
            emit({"type": "agent_start", "agent": "FinalWriter", "task": "融合证据并撰写最终报告"})
            report = ""
            if state.status is ResearchStatus.BUDGET_EXCEEDED:
                # A hard budget is terminal. Preserve the best checkpointed
                # draft instead of spending more tokens or failing the stream.
                report = state.draft
                emit({"type": "report_replace", "content": report})
                emit({
                    "type": "budget_exceeded",
                    "message": state.stop_reason,
                    "budget": orchestrator.budget.summary(),
                })
            else:
                try:
                    async for delta in orchestrator._final_report_stream(
                        state.brief,
                        [note.content for note in state.notes],
                        state.draft,
                    ):
                        if cancel_event.is_set():
                            return _cancelled_update()
                        report += delta
                        emit({"type": "text", "content": delta})
                except Exception as exc:
                    logger.warning(
                        "[DeepResearch] FinalWriter unavailable (%s); using best draft",
                        type(exc).__name__,
                    )
                    report = state.draft
                    emit({
                        "type": "phase_status",
                        "phase": "research_warning",
                        "label": "FinalWriter 连接暂时不可用，已返回当前最佳草稿",
                    })
                    emit({"type": "report_replace", "content": report})

            linked_report = ensure_clickable_sources(report, state.evidence)
            if linked_report != report:
                report = linked_report
                emit({"type": "report_replace", "content": report})

            validator = CitationValidator()
            claims = validator.extract_claims(report)
            result = validator.validate(claims, state.evidence)
            url_issues = validator.validate_report_urls(report, state.evidence)
            issues = [*result.issues, *url_issues]
            validation = result.to_dict()
            validation["valid"] = not any(issue.severity == "error" for issue in issues)
            validation["issues"] = [issue.to_dict() for issue in issues]
            validation["evidence_count"] = len(state.evidence)
            if issues:
                invalid_urls = {issue.url for issue in issues if issue.url}
                cleaned = _remove_unverified_links(report, invalid_urls)
                if cleaned != report:
                    report = cleaned
                    validation["sanitized"] = True
                    emit({"type": "report_replace", "content": report})
            emit({"type": "citation_validation", **validation})
            evaluated_state = state.model_copy(deep=True)
            evaluated_state.final_report = report
            evaluated_state.claims = claims
            evaluated_state.citation_validation = validation
            evaluated_state.phase = ResearchPhase.COMPLETE
            evaluated_state.status = ResearchStatus.COMPLETED
            run_evaluation = evaluate_research_run(evaluated_state).to_dict()
            emit({"type": "deep_research_eval", **run_evaluation})
            emit({
                "type": "agent_done",
                "agent": "FinalWriter",
                "summary": report[:300] + ("…" if len(report) > 300 else ""),
                "stop_reason": "最终报告生成并完成引用校验",
            })
            return {
                "final_report": report,
                "claims": [claim.to_dict() for claim in claims],
                "citation_validation": validation,
                "run_evaluation": run_evaluation,
                "phase": ResearchPhase.COMPLETE.value,
                "status": ResearchStatus.COMPLETED.value,
                "usage": orchestrator.budget.usage.model_dump(mode="json"),
            }

        builder = StateGraph(ResearchState)
        builder.add_node("brief", brief_node)
        builder.add_node("draft", draft_node)
        builder.add_node("supervisor", supervisor_node)
        builder.add_node("final", final_node)
        builder.add_edge(START, "brief")
        builder.add_edge("brief", "draft")
        builder.add_edge("draft", "supervisor")
        builder.add_conditional_edges("supervisor", route_after_supervisor)
        builder.add_edge("final", END)
        return builder.compile(checkpointer=checkpointer, name="DeepResearchGraph")

    async def run_stream(
        self,
        task: str,
        *,
        run_id: str,
    ) -> AsyncGenerator[dict, None]:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        config = {"configurable": {"thread_id": run_id}}
        async with _DeepResearchSqliteSaver.from_conn_string(
            str(self.checkpoint_path)
        ) as saver:
            await saver.setup()
            graph = self._build(saver)
            snapshot = await graph.aget_state(config)
            if snapshot.values:
                restored_usage = ResearchState.model_validate(snapshot.values).usage
                self.orchestrator.budget.usage = restored_usage
            if snapshot.values and not snapshot.next:
                restored = ResearchState.model_validate(snapshot.values)
                if restored.status is ResearchStatus.COMPLETED:
                    yield {"type": "run_resumed", "run_id": run_id, "phase": "complete"}
                    yield {"type": "text", "content": restored.final_report}
                    yield {"type": "citation_validation", **restored.citation_validation}
                    yield {"type": "done"}
                    return

            graph_input = None if snapshot.values and snapshot.next else ResearchState(
                run_id=run_id,
                task=task,
                status=ResearchStatus.RUNNING,
            ).to_checkpoint()
            if graph_input is None:
                yield {
                    "type": "run_resumed",
                    "run_id": run_id,
                    "phase": snapshot.next[0] if snapshot.next else "unknown",
                }
            else:
                yield {"type": "run_started", "run_id": run_id}

            async for mode, chunk in graph.astream(
                graph_input,
                config,
                stream_mode=["custom", "updates"],
            ):
                if mode == "custom":
                    yield chunk

            final_snapshot = await graph.aget_state(config)
            final_state = ResearchState.model_validate(final_snapshot.values)
            yield {
                "type": "research_state",
                "run_id": run_id,
                "phase": final_state.phase.value,
                "status": final_state.status.value,
                "iteration": final_state.iteration,
                "evidence_count": len(final_state.evidence),
                "open_critiques": len(final_state.open_critiques),
                "budget": self.orchestrator.budget.summary(),
            }
            yield {"type": "done"}


def _cancelled_update() -> dict:
    return {
        "phase": ResearchPhase.CANCELLED.value,
        "status": ResearchStatus.CANCELLED.value,
        "stop_reason": "cancelled by user or disconnected client",
        "cancel_requested": True,
    }


def _remove_unverified_links(report: str, invalid_urls: set[str]) -> str:
    if not invalid_urls:
        return report

    def replace(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        return label if url in invalid_urls else match.group(0)

    return re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", replace, report)


__all__ = ["DeepResearchGraphRuntime"]
