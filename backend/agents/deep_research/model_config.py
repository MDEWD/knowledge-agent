"""Role-level model configuration for the DeepResearch pipeline."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DeepResearchModels:
    """Model handles used by each DeepResearch role."""

    draft: str
    supervisor: str
    researcher_main: str
    researcher_summarizer: str
    researcher_compressor: str
    red_team: str
    evaluator: str
    writer: str

    @classmethod
    def from_env(cls, default_model: str) -> "DeepResearchModels":
        """Load role models, falling back to the application default."""

        def role(name: str) -> str:
            return os.environ.get(f"DEEP_RESEARCH_{name}_MODEL", default_model)

        return cls(
            draft=role("DRAFT"),
            supervisor=role("SUPERVISOR"),
            researcher_main=role("RESEARCHER_MAIN"),
            researcher_summarizer=role("RESEARCHER_SUMMARIZER"),
            researcher_compressor=role("RESEARCHER_COMPRESSOR"),
            red_team=role("RED_TEAM"),
            evaluator=role("EVALUATOR"),
            writer=role("WRITER"),
        )
