"""
Checkpoint: persist agent-run state to disk and resume after failure.

Design:
  - Checkpoint is a plain dataclass (JSON-serialisable).
  - CheckpointStore handles all I/O; callers never touch the filesystem directly.
  - Each run is identified by a stable run_id (e.g. UUID).  A new Checkpoint
    overwrites any previous checkpoint for the same run_id.
  - load() returns None when no checkpoint exists, letting the caller decide
    whether to start fresh.

Usage:
    store = CheckpointStore("/tmp/agent_checkpoints")

    # Save after every completed step
    cp = Checkpoint(run_id="abc", task="...", step=2, history=[...])
    store.save(cp)

    # On startup, attempt resume
    cp = store.load("abc")
    if cp:
        start_step = cp.step
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """Snapshot of an in-progress agent run."""
    run_id: str
    task: str
    step: int                                  # next step to execute (0-based)
    history: list[dict]                        # messages accumulated so far
    metadata: dict = field(default_factory=dict)
    saved_at: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "Checkpoint":
        data = json.loads(raw)
        return cls(**data)


class CheckpointStore:
    """
    File-backed store: one JSON file per run_id under `directory`.

    The directory is created on first use; missing files return None rather
    than raising, making "start fresh" the natural code path.
    """

    def __init__(self, directory: str | Path = "data/checkpoints") -> None:
        self._dir = Path(directory)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def save(self, checkpoint: Checkpoint) -> None:
        """Atomically write (via temp-file rename) a checkpoint to disk."""
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._path(checkpoint.run_id)
        tmp = target.with_suffix(".tmp")
        try:
            tmp.write_text(checkpoint.to_json(), encoding="utf-8")
            tmp.replace(target)
            logger.debug("[checkpoint] saved run=%s step=%d", checkpoint.run_id, checkpoint.step)
        except OSError as exc:
            logger.warning("[checkpoint] failed to save run=%s: %s", checkpoint.run_id, exc)
            tmp.unlink(missing_ok=True)
            raise

    def load(self, run_id: str) -> Checkpoint | None:
        """Return the most recent checkpoint for run_id, or None."""
        path = self._path(run_id)
        if not path.exists():
            return None
        try:
            cp = Checkpoint.from_json(path.read_text(encoding="utf-8"))
            logger.info("[checkpoint] resuming run=%s from step=%d", run_id, cp.step)
            return cp
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("[checkpoint] corrupt checkpoint for run=%s: %s", run_id, exc)
            return None

    def delete(self, run_id: str) -> None:
        """Remove checkpoint once a run completes successfully."""
        self._path(run_id).unlink(missing_ok=True)
        logger.debug("[checkpoint] deleted run=%s", run_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _path(self, run_id: str) -> Path:
        # Sanitise run_id so it is safe as a filename.
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in run_id)
        return self._dir / f"{safe}.json"
