"""Deterministic citation checks for generated research claims."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Iterable

from .evidence import Citation, Claim, Evidence, normalize_url


@dataclass(slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: str = "error"
    claim_id: str = ""
    source_id: str = ""
    url: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class CitationValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)
    total_claims: int = 0
    supported_critical_claims: int = 0

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def critical_claim_coverage(self) -> float:
        critical_count = sum(
            1 for issue in self.issues if issue.code == "critical_claim_without_evidence"
        ) + self.supported_critical_claims
        return 1.0 if critical_count == 0 else self.supported_critical_claims / critical_count

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "total_claims": self.total_claims,
            "supported_critical_claims": self.supported_critical_claims,
            "critical_claim_coverage": self.critical_claim_coverage,
            "issues": [issue.to_dict() for issue in self.issues],
        }


class CitationValidator:
    """Validate claims against only the evidence actually gathered in this run."""

    def validate(
        self,
        claims: Iterable[Claim],
        evidence: Iterable[Evidence],
    ) -> CitationValidationResult:
        claim_list = list(claims)
        evidence_list = list(evidence)
        result = CitationValidationResult(total_claims=len(claim_list))
        by_id = {item.source_id: item for item in evidence_list}
        by_url = {normalize_url(item.url): item for item in evidence_list if item.url}

        url_counts = Counter(normalize_url(item.url) for item in evidence_list if item.url)
        for url, count in url_counts.items():
            if count > 1:
                result.issues.append(ValidationIssue(
                    code="duplicate_source",
                    severity="warning",
                    message=f"同一来源重复出现 {count} 次",
                    url=url,
                ))

        for claim in claim_list:
            valid_source_ids: set[str] = set()
            for citation in claim.citations:
                source = by_id.get(citation.source_id) if citation.source_id else None
                if source is None and citation.url:
                    source = by_url.get(normalize_url(citation.url))
                if source is None:
                    code = "unknown_url" if citation.url else "unknown_source"
                    result.issues.append(ValidationIssue(
                        code=code,
                        message="引用未出现在本次研究的证据集中",
                        claim_id=claim.claim_id,
                        source_id=citation.source_id,
                        url=citation.url,
                    ))
                else:
                    valid_source_ids.add(source.source_id)

            if len(valid_source_ids) < len([
                citation for citation in claim.citations
                if (citation.source_id in by_id) or (citation.url and normalize_url(citation.url) in by_url)
            ]):
                result.issues.append(ValidationIssue(
                    code="duplicate_citation",
                    severity="warning",
                    message="同一 Claim 重复引用了相同来源",
                    claim_id=claim.claim_id,
                ))

            if claim.critical and not valid_source_ids:
                result.issues.append(ValidationIssue(
                    code="critical_claim_without_evidence",
                    message="关键结论没有可验证证据",
                    claim_id=claim.claim_id,
                ))
            elif claim.critical:
                result.supported_critical_claims += 1

        return result

    def validate_report_urls(
        self,
        report_markdown: str,
        evidence: Iterable[Evidence],
    ) -> list[ValidationIssue]:
        """Reject Markdown links hallucinated by the writer."""
        known = {normalize_url(item.url) for item in evidence if item.url}
        urls = re.findall(r"\[[^\]]*\]\((https?://[^\s)]+)\)", report_markdown or "")
        return [
            ValidationIssue(
                code="unknown_url",
                message="报告链接未出现在本次研究的证据集中",
                url=url,
            )
            for url in dict.fromkeys(urls)
            if normalize_url(url) not in known
        ]

    def extract_claims(self, report_markdown: str) -> list[Claim]:
        """Convert report paragraphs into checkpoint-safe claims and citations.

        This is deliberately deterministic: citation validation must not depend
        on a second model inventing or omitting the claims it is meant to audit.
        """
        claims: list[Claim] = []
        for block in re.split(r"\n\s*\n", report_markdown or ""):
            text = "\n".join(
                line for line in block.strip().splitlines()
                if not line.lstrip().startswith("#")
            ).strip()
            if not text:
                continue
            links = re.findall(r"\[[^\]]*\]\((https?://[^\s)]+)\)", text)
            plain = re.sub(r"\[([^\]]*)\]\(https?://[^\s)]+\)", r"\1", text)
            plain = re.sub(r"^[>*\-\d.\s]+", "", plain).strip()
            if not plain:
                continue
            claims.append(Claim.create(
                plain,
                critical=True,
                citations=[Citation(url=url) for url in dict.fromkeys(links)],
            ))
        return claims
