"""Structured evidence primitives used by the DeepResearch pipeline.

The types in this module deliberately have no framework dependency.  They can
be serialized into a LangGraph checkpoint, SSE payload, or JSON document
without custom encoders.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
    "spm",
}


def normalize_url(url: str) -> str:
    """Return a stable URL identity while retaining content-changing params."""
    value = (url or "").strip()
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.scheme or not parts.netloc:
        return value.rstrip("/")

    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        hostname = f"{hostname}:{port}"
    path = parts.path.rstrip("/") or "/"
    query = urlencode(
        sorted(
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_QUERY_KEYS
        ),
        doseq=True,
    )
    return urlunsplit((scheme, hostname, path, query, ""))


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


@dataclass(slots=True)
class Evidence:
    source_id: str
    url: str
    title: str
    query: str
    snippet: str = ""
    raw_content: str = ""
    published_at: str | None = None
    source_type: str = "web"
    authority_score: float = 0.0
    freshness_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.url = normalize_url(self.url)
        if not self.source_id:
            identity = self.url or f"{self.title}\n{self.query}\n{self.snippet}"
            self.source_id = stable_id("src", identity)
        self.authority_score = max(0.0, min(1.0, float(self.authority_score)))
        self.freshness_score = max(0.0, min(1.0, float(self.freshness_score)))

    @classmethod
    def create(cls, *, url: str, title: str, query: str, **kwargs: Any) -> "Evidence":
        canonical = normalize_url(url)
        identity = canonical or f"{title}\n{query}\n{kwargs.get('snippet', '')}"
        return cls(
            source_id=stable_id("src", identity),
            url=canonical,
            title=title,
            query=query,
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        return cls(**data)


@dataclass(slots=True)
class Citation:
    """A claim's pointer to a source.  Either source_id or URL may resolve it."""

    source_id: str = ""
    url: str = ""
    excerpt: str = ""

    def __post_init__(self) -> None:
        self.url = normalize_url(self.url)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Citation":
        return cls(**data)


@dataclass(slots=True)
class Claim:
    claim_id: str
    text: str
    critical: bool = True
    citations: list[Citation] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.claim_id:
            self.claim_id = stable_id("claim", self.text.strip())
        self.citations = [
            item if isinstance(item, Citation) else Citation.from_dict(item)
            for item in self.citations
        ]

    @classmethod
    def create(
        cls,
        text: str,
        *,
        critical: bool = True,
        citations: Iterable[Citation] = (),
    ) -> "Claim":
        return cls("", text, critical, list(citations))

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "critical": self.critical,
            "citations": [citation.to_dict() for citation in self.citations],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Claim":
        return cls(
            claim_id=data.get("claim_id", ""),
            text=data.get("text", ""),
            critical=bool(data.get("critical", True)),
            citations=[Citation.from_dict(item) for item in data.get("citations", [])],
        )


class EvidenceLedger:
    """Globally de-duplicated, checkpoint-friendly collection of evidence."""

    def __init__(self, evidence: Iterable[Evidence] = ()) -> None:
        self._by_id: dict[str, Evidence] = {}
        self._id_by_url: dict[str, str] = {}
        for item in evidence:
            self.add(item)

    def add(self, evidence: Evidence) -> Evidence:
        existing_id = self._id_by_url.get(evidence.url) if evidence.url else None
        existing = self._by_id.get(existing_id or evidence.source_id)
        if existing is None:
            self._by_id[evidence.source_id] = evidence
            if evidence.url:
                self._id_by_url[evidence.url] = evidence.source_id
            return evidence

        # Keep stable identity while enriching a source seen by another query.
        if len(evidence.raw_content) > len(existing.raw_content):
            existing.raw_content = evidence.raw_content
        if len(evidence.snippet) > len(existing.snippet):
            existing.snippet = evidence.snippet
        existing.authority_score = max(existing.authority_score, evidence.authority_score)
        existing.freshness_score = max(existing.freshness_score, evidence.freshness_score)
        queries = set(existing.metadata.get("queries", [existing.query]))
        queries.add(evidence.query)
        existing.metadata["queries"] = sorted(query for query in queries if query)
        return existing

    def get(self, source_id: str) -> Evidence | None:
        return self._by_id.get(source_id)

    def values(self) -> list[Evidence]:
        return list(self._by_id.values())

    def to_dict(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.values()]

    @classmethod
    def from_dict(cls, data: list[dict[str, Any]]) -> "EvidenceLedger":
        return cls(Evidence.from_dict(item) for item in data)

    def __len__(self) -> int:
        return len(self._by_id)
