"""
Blackboard: shared state bus for inter-agent communication.

ResearchAgent posts findings after completing its run.
AnalysisAgent reads the research context and may call
request_additional_research() to fill gaps (up to max_gap_requests times).
Each gap result is appended back to the blackboard so WritingAgent inherits
the full enriched context via the analysis result.

Checkpoint integration
----------------------
to_dict() / from_dict() allow the blackboard state to be serialised into the
orchestrator's CheckpointStore so a resumed run starts with the same context
that was available when the session was interrupted.
"""
from __future__ import annotations

import time


class Blackboard:
    """Shared state for inter-agent communication within one orchestrator run."""

    def __init__(self, max_gap_requests: int = 3) -> None:
        self.max_gap_requests = max_gap_requests
        self._findings: list[dict] = []
        self._gaps: list[dict] = []
        self._gap_count: int = 0

    # ── Write ─────────────────────────────────────────────────────────────────

    def post_finding(self, agent: str, topic: str, content: str) -> None:
        """Record a research finding from any agent."""
        self._findings.append({
            "agent": agent,
            "topic": topic,
            "content": content,
            "ts": time.time(),
        })

    def add_gap(self, topic: str, reason: str, result: str) -> None:
        """Record a gap-fill request and its result; re-post as a new finding."""
        self._gaps.append({"topic": topic, "reason": reason, "result": result})
        self._gap_count += 1
        # Append to findings so context stays current for downstream agents
        self._findings.append({
            "agent": "ResearchAgent",
            "topic": f"[追加] {topic}",
            "content": result,
            "ts": time.time(),
        })

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_research_context(self) -> str:
        """Format all findings as an LLM-injectable context block."""
        if not self._findings:
            return ""
        parts = [
            f"=== [{f['agent']}] 关于「{f['topic']}」的研究 ===\n{f['content']}"
            for f in self._findings
        ]
        return "\n\n".join(parts)

    def can_request_gap(self) -> bool:
        return self._gap_count < self.max_gap_requests

    def gap_count(self) -> int:
        return self._gap_count

    def finding_count(self) -> int:
        return len(self._findings)

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "findings": list(self._findings),
            "gaps": list(self._gaps),
            "gap_count": self._gap_count,
        }

    @classmethod
    def from_dict(cls, data: dict, max_gap_requests: int = 3) -> "Blackboard":
        bb = cls(max_gap_requests=max_gap_requests)
        bb._findings = data.get("findings", [])
        bb._gaps = data.get("gaps", [])
        bb._gap_count = data.get("gap_count", 0)
        return bb
