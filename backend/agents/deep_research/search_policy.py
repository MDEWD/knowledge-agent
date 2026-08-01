"""Search quality policy: de-duplication, scoring, and stable cache keys."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit

from .evidence import Evidence, normalize_url


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip()).casefold()


@dataclass(slots=True)
class SearchQualityPolicy:
    """Run-scoped policy state that is safe to serialize into a checkpoint."""

    seen_queries: set[str] = field(default_factory=set)
    seen_urls: set[str] = field(default_factory=set)

    def accept_query(self, query: str) -> bool:
        normalized = normalize_query(query)
        if not normalized or normalized in self.seen_queries:
            return False
        self.seen_queries.add(normalized)
        return True

    def accept_url(self, url: str) -> bool:
        normalized = normalize_url(url)
        if not normalized or normalized in self.seen_urls:
            return False
        self.seen_urls.add(normalized)
        return True

    def deduplicate_queries(self, queries: Iterable[str]) -> list[str]:
        return [query for query in queries if self.accept_query(query)]

    def deduplicate_evidence(self, evidence: Iterable[Evidence]) -> list[Evidence]:
        return [item for item in evidence if self.accept_url(item.url)]

    @staticmethod
    def authority_score(url: str, source_type: str = "web") -> float:
        kind = (source_type or "web").casefold()
        type_scores = {
            "government": 1.0,
            "regulator": 1.0,
            "official": 0.95,
            "academic": 0.92,
            "paper": 0.92,
            "company": 0.82,
            "knowledge_base": 0.78,
            "news": 0.68,
            "web": 0.55,
            "blog": 0.38,
            "social": 0.25,
        }
        score = type_scores.get(kind, 0.5)
        host = (urlsplit(url).hostname or "").casefold()
        if host.endswith(".gov") or ".gov." in host or host.endswith(".gov.cn"):
            score = max(score, 1.0)
        elif host.endswith(".edu") or ".edu." in host or host.endswith(".ac.cn"):
            score = max(score, 0.92)
        return score

    @staticmethod
    def freshness_score(published_at: str | None, *, now: date | None = None) -> float:
        if not published_at:
            return 0.5
        try:
            normalized = published_at.replace("Z", "+00:00")
            published = datetime.fromisoformat(normalized).date()
        except (TypeError, ValueError):
            try:
                published = date.fromisoformat(published_at[:10])
            except (TypeError, ValueError):
                return 0.5
        age_days = max(0, ((now or datetime.now(timezone.utc).date()) - published).days)
        if age_days <= 30:
            return 1.0
        if age_days <= 90:
            return 0.9
        if age_days <= 365:
            return 0.75
        if age_days <= 3 * 365:
            return 0.55
        return 0.35

    def score(self, evidence: Evidence, *, now: date | None = None) -> float:
        evidence.authority_score = self.authority_score(evidence.url, evidence.source_type)
        evidence.freshness_score = self.freshness_score(evidence.published_at, now=now)
        return round(evidence.authority_score * 0.65 + evidence.freshness_score * 0.35, 4)

    @staticmethod
    def cache_key(
        query: str,
        *,
        provider: str = "tavily",
        options: dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "provider": provider.casefold().strip(),
            "query": normalize_query(query),
            "options": options or {},
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "search_" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "seen_queries": sorted(self.seen_queries),
            "seen_urls": sorted(self.seen_urls),
        }

    @classmethod
    def from_dict(cls, data: dict[str, list[str]]) -> "SearchQualityPolicy":
        return cls(
            seen_queries=set(data.get("seen_queries", [])),
            seen_urls=set(data.get("seen_urls", [])),
        )
