"""
Skill store: persist and semantically retrieve agent skills.

Storage layout
  data/skills/
    index.json          — lightweight index (id, name, tags, created_at)
    <skill_id>.json     — full Skill payload

Retrieval uses TF-IDF cosine similarity over the skill description +
procedure text.  For a project of this scale a full vector DB would be
premature; TF-IDF is fast, zero-dependency, and interpretable.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill value object
# ---------------------------------------------------------------------------

@dataclass
class Skill:
    """
    A verified, reusable solution pattern.

    Fields
    ------
    skill_id    : Stable UUID string.
    name        : Short, descriptive title (≤ 60 chars).
    description : One-paragraph explanation of what the skill does.
    procedure   : Step-by-step instructions the agent can follow.
    tags        : Free-form keywords for coarse filtering.
    source_task : The original task that produced this skill.
    created_at  : Unix timestamp.
    use_count   : Incremented each time the skill is retrieved and used.
    """
    skill_id: str
    name: str
    description: str
    procedure: str
    tags: list[str] = field(default_factory=list)
    source_task: str = ""
    created_at: float = field(default_factory=time.time)
    use_count: int = 0
    effectiveness_score: float = 0.5  # EMA of rubric scores after injection (0-1)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "Skill":
        return cls(**json.loads(raw))

    def to_prompt_block(self) -> str:
        """Format the skill as a context block for the agent system prompt."""
        return (
            f"### Skill: {self.name}\n"
            f"{self.description}\n\n"
            f"**Procedure**:\n{self.procedure}"
        )


# ---------------------------------------------------------------------------
# TF-IDF retriever (no external dependencies)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z一-鿿]+", text.lower())


class _TfidfIndex:
    """Minimal in-memory TF-IDF index for skill retrieval."""

    def __init__(self) -> None:
        self._docs: dict[str, list[str]] = {}   # skill_id → tokens
        self._df: Counter = Counter()           # document frequency per term

    def add(self, skill_id: str, text: str) -> None:
        tokens = _tokenize(text)
        self._docs[skill_id] = tokens
        for term in set(tokens):
            self._df[term] += 1

    def remove(self, skill_id: str) -> None:
        if skill_id not in self._docs:
            return
        tokens = set(self._docs.pop(skill_id))
        for term in tokens:
            self._df[term] -= 1
            if self._df[term] == 0:
                del self._df[term]

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """Return [(skill_id, score)] sorted by descending similarity."""
        n = len(self._docs)
        if n == 0:
            return []

        q_tokens = _tokenize(query)
        q_tf = Counter(q_tokens)
        q_norm = math.sqrt(sum(v * v for v in q_tf.values()))
        if q_norm == 0:
            return []

        scores: dict[str, float] = defaultdict(float)
        for term, q_count in q_tf.items():
            if term not in self._df:
                continue
            idf = math.log((n + 1) / (self._df[term] + 1)) + 1
            q_weight = (q_count / q_norm) * idf
            for skill_id, tokens in self._docs.items():
                d_tf = tokens.count(term)
                if d_tf == 0:
                    continue
                d_norm = math.sqrt(sum(tokens.count(t) ** 2 for t in set(tokens)))
                d_weight = (d_tf / d_norm) * idf
                scores[skill_id] += q_weight * d_weight

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


# ---------------------------------------------------------------------------
# SkillStore
# ---------------------------------------------------------------------------

class SkillStore:
    """
    Persistent skill library backed by a directory of JSON files.

    Thread-safety: single-process asyncio is fine; the GIL covers the
    in-memory index, and writes use atomic rename.
    """

    def __init__(self, directory: str | Path = "data/skills") -> None:
        self._dir = Path(directory)
        self._index: dict[str, dict] = {}   # skill_id → index entry
        self._tfidf = _TfidfIndex()
        self._load_index()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def save(self, skill: Skill) -> None:
        """Persist a new or updated skill and rebuild its index entry."""
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._skill_path(skill.skill_id)
        tmp = target.with_suffix(".tmp")
        try:
            tmp.write_text(skill.to_json(), encoding="utf-8")
            tmp.replace(target)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise

        # Update in-memory index
        self._tfidf.remove(skill.skill_id)
        self._tfidf.add(skill.skill_id, f"{skill.name} {skill.description} {skill.procedure}")
        self._index[skill.skill_id] = {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "tags": skill.tags,
            "created_at": skill.created_at,
            "use_count": skill.use_count,
        }
        self._save_index()
        logger.info("[skills] saved skill_id=%s name=%r", skill.skill_id, skill.name)

    def get(self, skill_id: str) -> Skill | None:
        path = self._skill_path(skill_id)
        if not path.exists():
            return None
        try:
            return Skill.from_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("[skills] corrupt skill %s: %s", skill_id, exc)
            return None

    def search(self, query: str, top_k: int = 5) -> list[Skill]:
        """Return the top_k most relevant skills and increment their use_count."""
        hits = self._tfidf.search(query, top_k)
        skills: list[Skill] = []
        for skill_id, _score in hits:
            skill = self.get(skill_id)
            if skill is None:
                continue
            skill.use_count += 1
            self.save(skill)
            skills.append(skill)
        return skills

    def record_outcome(self, skill_ids: list[str], score: float) -> None:
        """Update effectiveness score (EMA) for skills used in a completed run."""
        for sid in skill_ids:
            skill = self.get(sid)
            if skill is None:
                continue
            skill.effectiveness_score = round(
                0.7 * skill.effectiveness_score + 0.3 * score, 3
            )
            self.save(skill)
            logger.debug(
                "[skills] outcome skill_id=%s score=%.2f new_eff=%.3f",
                sid, score, skill.effectiveness_score,
            )

    def list_all(self) -> list[dict]:
        """Return all index entries (lightweight — no skill bodies)."""
        return sorted(self._index.values(), key=lambda e: e["created_at"], reverse=True)

    def delete(self, skill_id: str) -> None:
        self._skill_path(skill_id).unlink(missing_ok=True)
        self._tfidf.remove(skill_id)
        self._index.pop(skill_id, None)
        self._save_index()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _skill_path(self, skill_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in skill_id)
        return self._dir / f"{safe}.json"

    def _index_path(self) -> Path:
        return self._dir / "index.json"

    def _load_index(self) -> None:
        path = self._index_path()
        if not path.exists():
            return
        try:
            entries: list[dict] = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for entry in entries:
            skill_id = entry.get("skill_id")
            if not skill_id:
                continue
            self._index[skill_id] = entry
            skill = self.get(skill_id)
            if skill:
                self._tfidf.add(
                    skill_id,
                    f"{skill.name} {skill.description} {skill.procedure}",
                )

    def _save_index(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._index_path().with_suffix(".tmp")
        tmp.write_text(
            json.dumps(list(self._index.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._index_path())
