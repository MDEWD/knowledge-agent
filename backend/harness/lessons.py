"""
Lesson store — the heart of Harness Engineering.

Mitchell Hashimoto's definition:
    "Anytime you find an agent makes a mistake, you take the time to
     engineer a solution such that the agent will not make that mistake
     again in the future."

This module makes that concrete:
  - Every agent failure is recorded as a Lesson.
  - Before the next run, relevant lessons are surfaced in the agent's
    context so it walks in already knowing what NOT to do.
  - Lessons accumulate over time, making the harness smarter with each run.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Lesson:
    """One learned failure: what went wrong and how to avoid it."""
    id: str
    error_type: str           # class name of the exception
    root_cause: str           # concise description of what triggered the failure
    fix: str                  # concrete instruction for the agent to self-correct
    pattern_keywords: list[str]    # keywords extracted from failing tasks
    examples: list[str] = field(default_factory=list)   # truncated task samples
    hit_count: int = 1
    created_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)


class LessonStore:
    """
    Persists agent failure lessons to disk and answers relevance queries.

    Usage
    -----
    store = LessonStore("data/harness_lessons.json")

    # After a failure:
    store.record(task, exc, fix_hint="Shorten input to <500 words")

    # Before a run:
    lessons = store.query(task, top_k=3)
    """

    def __init__(self, path: str | Path = "data/harness_lessons.json") -> None:
        self._path = Path(path)
        self._lessons: dict[str, Lesson] = {}
        self._load()

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def record(
        self,
        task: str,
        error: Exception,
        fix_hint: str = "",
    ) -> Lesson:
        """
        Record a failure.  If a similar lesson exists (same error type +
        overlapping keywords), update its hit count; otherwise create a new one.
        Returns the lesson (new or updated).
        """
        error_type = type(error).__name__
        error_msg = str(error)[:400]
        keywords = _keywords(task)

        existing = self._find_similar(keywords, error_type)
        if existing:
            existing.hit_count += 1
            existing.last_seen_at = time.time()
            if task[:200] not in existing.examples:
                existing.examples.append(task[:200])
            self._save()
            logger.debug("[lessons] updated lesson %s (hits=%d)", existing.id, existing.hit_count)
            return existing

        lesson = Lesson(
            id=str(uuid.uuid4())[:8],
            error_type=error_type,
            root_cause=error_msg,
            fix=fix_hint or f"Agent triggered {error_type}. Review constraints before retrying.",
            pattern_keywords=keywords,
            examples=[task[:200]],
        )
        self._lessons[lesson.id] = lesson
        self._save()
        logger.info("[lessons] new lesson %s: %s", lesson.id, error_type)
        return lesson

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def query(self, task: str, top_k: int = 5) -> list[Lesson]:
        """Return lessons most relevant to the current task (by keyword overlap)."""
        task_words = set(_keywords(task))
        scored: list[tuple[float, Lesson]] = []
        for lesson in self._lessons.values():
            overlap = len(task_words & set(lesson.pattern_keywords))
            if overlap:
                score = overlap + lesson.hit_count * 0.1
                scored.append((score, lesson))
        scored.sort(key=lambda x: -x[0])
        return [l for _, l in scored[:top_k]]

    def all(self) -> list[Lesson]:
        return sorted(self._lessons.values(), key=lambda l: -l.hit_count)

    def clear(self) -> None:
        self._lessons.clear()
        self._save()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_similar(self, keywords: list[str], error_type: str) -> Lesson | None:
        kw_set = set(keywords)
        for lesson in self._lessons.values():
            if lesson.error_type != error_type:
                continue
            overlap = len(kw_set & set(lesson.pattern_keywords))
            if overlap >= 2:
                return lesson
        return None

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps({lid: asdict(l) for lid, l in self._lessons.items()},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except OSError as exc:
            logger.warning("[lessons] failed to persist: %s", exc)
            tmp.unlink(missing_ok=True)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._lessons = {lid: Lesson(**v) for lid, v in data.items()}
            logger.debug("[lessons] loaded %d lessons", len(self._lessons))
        except Exception as exc:
            logger.warning("[lessons] failed to load lessons: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _keywords(text: str, max_words: int = 12) -> list[str]:
    """Extract meaningful keywords from a task string."""
    tokens = re.findall(r'[a-zA-Z一-鿿]{2,}', text.lower())
    _stop = {"the", "a", "an", "is", "in", "of", "to", "and", "for", "with",
              "that", "this", "it", "on", "at", "by", "be", "are", "was"}
    return [t for t in tokens if t not in _stop][:max_words]
