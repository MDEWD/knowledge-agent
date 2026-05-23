"""
AgentContext — surfaces harness lessons to agents before each run.

Implements the "Maps over Manuals" principle from Harness Engineering:
a concise, always-current brief that tells the agent what's known to
go wrong and exactly how to avoid it — injected as a system-prompt
prefix so the agent starts informed, not naive.
"""
from __future__ import annotations

from .lessons import Lesson, LessonStore


class AgentContextBuilder:
    """
    Builds a system-prompt prefix from accumulated harness lessons.

    Usage
    -----
    builder = AgentContextBuilder(lesson_store)
    prefix  = builder.build(task)
    # prepend prefix to the agent's system prompt
    """

    def __init__(self, lesson_store: LessonStore | None = None) -> None:
        self._store = lesson_store

    def build(self, task: str, top_k: int = 3) -> str:
        """
        Return a markdown-formatted system-prompt prefix.
        Empty string when there are no relevant lessons.
        """
        if not self._store:
            return ""

        lessons = self._store.query(task, top_k=top_k)
        if not lessons:
            return ""

        lines = [
            "## Harness: known failure modes for this task\n",
            "The following mistakes have been made before on similar tasks. "
            "Read each one and actively avoid repeating it.\n",
        ]
        for i, lesson in enumerate(lessons, 1):
            lines.append(
                f"{i}. **{lesson.error_type}** (seen {lesson.hit_count}x)\n"
                f"   Cause: {lesson.root_cause}\n"
                f"   Fix:   {lesson.fix}\n"
            )
        lines.append(
            "Follow the fixes above before taking any action. "
            "If unsure, ask for clarification rather than guessing.\n\n"
        )
        return "\n".join(lines)

    @staticmethod
    def format_lessons_report(lessons: list[Lesson]) -> str:
        """Human-readable report of all accumulated lessons (for /api/harness/lessons)."""
        if not lessons:
            return "No lessons recorded yet."
        rows = []
        for l in lessons:
            rows.append(
                f"[{l.id}] {l.error_type} ×{l.hit_count}\n"
                f"  Cause : {l.root_cause[:120]}\n"
                f"  Fix   : {l.fix}\n"
                f"  Seen  : {', '.join(l.examples[:2])}"
            )
        return "\n\n".join(rows)
