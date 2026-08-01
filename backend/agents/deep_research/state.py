"""Typed, checkpoint-safe state for the DeepResearch LangGraph."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from agents.deep_research.budget import UsageLedger
from agents.deep_research.evidence import Claim, Evidence


class ResearchPhase(str, Enum):
    INITIALIZING = "initializing"
    BRIEFING = "briefing"
    PLANNING = "planning"
    RESEARCHING = "researching"
    SYNTHESIZING = "synthesizing"
    RED_TEAM = "red_team"
    EVALUATING = "evaluating"
    FINALIZING = "finalizing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"


class CritiqueStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class CritiqueSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CritiqueCategory(str, Enum):
    FACT = "fact"
    CITATION = "citation"
    LOGIC = "logic"
    COVERAGE = "coverage"


class ResearchNote(BaseModel):
    topic: str = ""
    content: str
    evidence_ids: list[str] = Field(default_factory=list)
    iteration: int = Field(default=0, ge=0)


class Critique(BaseModel):
    critique_id: str = Field(default_factory=lambda: f"crit_{uuid4().hex}")
    category: CritiqueCategory
    severity: CritiqueSeverity
    problem: str
    remediation: str = ""
    claim: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    status: CritiqueStatus = CritiqueStatus.OPEN
    resolution: str = ""
    created_iteration: int = Field(default=0, ge=0)
    closed_iteration: int | None = Field(default=None, ge=0)

    def resolve(self, resolution: str, *, iteration: int) -> None:
        if self.status is not CritiqueStatus.OPEN:
            raise ValueError(f"critique {self.critique_id} is already {self.status.value}")
        self.status = CritiqueStatus.RESOLVED
        self.resolution = resolution
        self.closed_iteration = iteration

    def reject(self, reason: str, *, iteration: int) -> None:
        if self.status is not CritiqueStatus.OPEN:
            raise ValueError(f"critique {self.critique_id} is already {self.status.value}")
        self.status = CritiqueStatus.REJECTED
        self.resolution = reason
        self.closed_iteration = iteration


class EvaluationSnapshot(BaseModel):
    iteration: int = Field(ge=0)
    comprehensiveness_score: float = Field(ge=0, le=10)
    accuracy_score: float = Field(ge=0, le=10)
    coherence_score: float = Field(ge=0, le=10)
    evidence_coverage: float = Field(default=0.0, ge=0, le=1)
    evidence_count: int = Field(default=0, ge=0)
    reason: str = ""

    @property
    def average(self) -> float:
        return (
            self.comprehensiveness_score
            + self.accuracy_score
            + self.coherence_score
        ) / 3


class ResearchState(BaseModel):
    """Canonical state passed between graph nodes and stored in checkpoints."""

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    schema_version: int = 1
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    task: str = ""
    phase: ResearchPhase = ResearchPhase.INITIALIZING
    iteration: int = Field(default=0, ge=0)
    brief: str = ""
    draft: str = ""
    final_report: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    notes: list[ResearchNote] = Field(default_factory=list)
    critiques: list[Critique] = Field(default_factory=list)
    evaluations: list[EvaluationSnapshot] = Field(default_factory=list)
    supervisor_messages: list[dict[str, Any]] = Field(default_factory=list)
    usage: UsageLedger = Field(default_factory=UsageLedger)
    query_history: list[str] = Field(default_factory=list)
    status: ResearchStatus = ResearchStatus.PENDING
    stop_reason: str = ""
    supervisor_requested_complete: bool = False
    citation_validation: dict[str, Any] = Field(default_factory=dict)
    run_evaluation: dict[str, Any] = Field(default_factory=dict)
    cancel_requested: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("evidence", mode="before")
    @classmethod
    def _restore_evidence(cls, value: Any) -> list[Evidence]:
        if value is None:
            return []
        return [item if isinstance(item, Evidence) else Evidence.from_dict(item) for item in value]

    @field_serializer("evidence")
    def _dump_evidence(self, value: list[Evidence]) -> list[dict[str, Any]]:
        return [item.to_dict() for item in value]

    @field_validator("claims", mode="before")
    @classmethod
    def _restore_claims(cls, value: Any) -> list[Claim]:
        if value is None:
            return []
        return [item if isinstance(item, Claim) else Claim.from_dict(item) for item in value]

    @field_serializer("claims")
    def _dump_claims(self, value: list[Claim]) -> list[dict[str, Any]]:
        return [item.to_dict() for item in value]

    @property
    def open_critiques(self) -> list[Critique]:
        return [item for item in self.critiques if item.status is CritiqueStatus.OPEN]

    @property
    def has_open_high_critique(self) -> bool:
        return any(item.severity is CritiqueSeverity.HIGH for item in self.open_critiques)

    @property
    def latest_evaluation(self) -> EvaluationSnapshot | None:
        return self.evaluations[-1] if self.evaluations else None

    def add_critique(self, critique: Critique) -> None:
        if any(item.critique_id == critique.critique_id for item in self.critiques):
            raise ValueError(f"duplicate critique_id: {critique.critique_id}")
        self.critiques.append(critique)
        self.touch()

    def resolve_critique(self, critique_id: str, resolution: str) -> Critique:
        critique = self._find_critique(critique_id)
        critique.resolve(resolution, iteration=self.iteration)
        self.touch()
        return critique

    def reject_critique(self, critique_id: str, reason: str) -> Critique:
        critique = self._find_critique(critique_id)
        critique.reject(reason, iteration=self.iteration)
        self.touch()
        return critique

    def _find_critique(self, critique_id: str) -> Critique:
        for item in self.critiques:
            if item.critique_id == critique_id:
                return item
        raise KeyError(f"unknown critique_id: {critique_id}")

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def to_checkpoint(self) -> dict[str, Any]:
        self.touch()
        return self.model_dump(mode="json")

    def to_checkpoint_json(self) -> str:
        return json.dumps(self.to_checkpoint(), ensure_ascii=False)

    @classmethod
    def from_checkpoint(cls, checkpoint: dict[str, Any]) -> "ResearchState":
        version = int(checkpoint.get("schema_version", 1))
        if version != 1:
            raise ValueError(f"unsupported ResearchState schema_version: {version}")
        return cls.model_validate(checkpoint)

    @classmethod
    def from_checkpoint_json(cls, payload: str) -> "ResearchState":
        return cls.from_checkpoint(json.loads(payload))
