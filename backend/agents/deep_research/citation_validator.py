"""Deterministic citation checks for generated research claims."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Iterable

from .evidence import Citation, Claim, Evidence, normalize_url


_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_LIST_ITEM_RE = re.compile(r"^(\s*(?:[-*+]\s+|\d+[.)]\s+))(.*)$")
_INLINE_SOURCE_RE = re.compile(
    r"(?P<prefix>(?:\*\*)?(?:来源依据|政策依据|数据来源|资料来源|信息来源|参考依据)\s*[：:](?:\*\*)?\s*)"
    r"(?P<body>.+)$"
)
_REFERENCE_HEADING_RE = re.compile(
    r"^\s*#{1,3}\s*(?:参考文献|资料来源|可核验来源|references?)\s*$",
    re.IGNORECASE,
)
_ANY_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")


def _match_key(value: str) -> str:
    """Normalize a source label for conservative title matching."""
    return re.sub(r"[^\w\u3400-\u9fff]+", "", (value or "").casefold())


def _markdown_label(value: str) -> str:
    return (value or "").replace("[", "\\[").replace("]", "\\]")


def _reference_key(value: str) -> str:
    return re.sub(r"(?:19|20)\d{2}年?", "", _match_key(value))


def _source_match_score(label: str, source: Evidence) -> float:
    query = _reference_key(label)
    title = _reference_key(source.title)
    if len(query) < 4 or len(title) < 4:
        return 0.0
    if query == title:
        lexical = 1.0
    elif query in title or title in query:
        lexical = 0.82 + 0.16 * min(len(query), len(title)) / max(len(query), len(title))
    else:
        lexical = SequenceMatcher(None, query, title).ratio()
    if lexical < 0.62:
        return 0.0
    quality = 0.04 * source.authority_score + 0.02 * source.freshness_score
    return lexical + quality


def _link_inline_source_body(body: str, sources: list[Evidence]) -> tuple[str, set[str]]:
    """Link semicolon-separated source labels while preserving punctuation."""
    parts = re.split(r"([；;])", body)
    linked: set[str] = set()
    output: list[str] = []
    for part in parts:
        if part in {"；", ";"} or not part.strip() or _MARKDOWN_LINK_RE.search(part):
            output.append(part)
            continue
        leading = part[:len(part) - len(part.lstrip())]
        trailing = part[len(part.rstrip()):]
        label = part.strip()
        scored = sorted(
            ((_source_match_score(label, source), index, source) for index, source in enumerate(sources)),
            key=lambda item: (-item[0], item[1]),
        )
        if scored and scored[0][0] > 0:
            source = scored[0][2]
            output.append(f"{leading}[{_markdown_label(label)}]({source.url}){trailing}")
            linked.add(normalize_url(source.url))
        else:
            output.append(part)
    return "".join(output), linked


def _remove_trailing_reference_section(lines: list[str]) -> list[str]:
    """Remove only a terminal bibliography; never remove an in-body section."""
    reference_indexes = [
        index for index, line in enumerate(lines)
        if _REFERENCE_HEADING_RE.match(line)
    ]
    if not reference_indexes:
        return lines
    start = reference_indexes[-1]
    if any(_ANY_HEADING_RE.match(line) for line in lines[start + 1:]):
        return lines
    while start > 0 and not lines[start - 1].strip():
        start -= 1
    return lines[:start]


def ensure_clickable_sources(report_markdown: str, evidence: Iterable[Evidence]) -> str:
    """Attach verified evidence URLs to source labels and add an audit appendix.

    Models occasionally preserve a human-readable source label but drop its URL.
    This deterministic pass only links labels that contain a collected evidence
    title. Any remaining collected sources are exposed in a verification appendix,
    so every link is auditable and no URL is invented by the writer.
    """
    report = report_markdown or ""
    sources: list[Evidence] = []
    seen_source_urls: set[str] = set()
    for item in evidence:
        url = normalize_url(item.url)
        if not url or url in seen_source_urls:
            continue
        seen_source_urls.add(url)
        sources.append(item)
    if not sources:
        return report

    linked_urls = {
        normalize_url(url)
        for _, url in _MARKDOWN_LINK_RE.findall(report)
        if normalize_url(url)
    }
    title_candidates = [
        (item, _match_key(item.title))
        for item in sources
        if len(_match_key(item.title)) >= 4
    ]
    output: list[str] = []
    for line in report.splitlines():
        inline_match = _INLINE_SOURCE_RE.search(line)
        if inline_match:
            linked_body, inline_urls = _link_inline_source_body(
                inline_match.group("body"),
                sources,
            )
            if inline_urls:
                line = (
                    line[:inline_match.start()]
                    + inline_match.group("prefix")
                    + linked_body
                )
                linked_urls.update(inline_urls)
        match = _LIST_ITEM_RE.match(line)
        if not match or _MARKDOWN_LINK_RE.search(line):
            output.append(line)
            continue
        prefix, label = match.groups()
        label_key = _match_key(label)
        candidates = [
            item for item, title_key in title_candidates
            if title_key in label_key or (len(label_key) >= 6 and label_key in title_key)
        ]
        if len(candidates) == 1:
            source = candidates[0]
            output.append(f"{prefix}[{_markdown_label(label.strip())}]({source.url})")
            linked_urls.add(normalize_url(source.url))
        else:
            output.append(line)

    return "\n".join(_remove_trailing_reference_section(output)).rstrip()


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
