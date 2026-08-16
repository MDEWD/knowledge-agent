from __future__ import annotations

import json
from datetime import date

from agents.deep_research.citation_validator import CitationValidator, ensure_clickable_sources
from agents.deep_research.evidence import Citation, Claim, Evidence, EvidenceLedger, normalize_url
from agents.deep_research.search_policy import SearchQualityPolicy


def evidence(url: str, **kwargs) -> Evidence:
    return Evidence.create(
        url=url,
        title=kwargs.pop("title", "SIA monthly report"),
        query=kwargs.pop("query", "semiconductor sales"),
        snippet=kwargs.pop("snippet", "Sales increased."),
        **kwargs,
    )


def test_evidence_round_trip_is_json_serializable_and_stable():
    item = evidence("HTTPS://Example.com/report/?utm_source=x&b=2&a=1#top")
    restored = Evidence.from_dict(json.loads(json.dumps(item.to_dict())))

    assert restored == item
    assert restored.url == "https://example.com/report?a=1&b=2"
    assert restored.source_id.startswith("src_")


def test_evidence_ledger_deduplicates_url_and_merges_queries():
    first = evidence("https://example.com/report?utm_source=a", query="query one")
    second = evidence(
        "https://example.com/report/",
        query="query two",
        raw_content="a much longer raw document",
    )
    ledger = EvidenceLedger([first, second])

    assert len(ledger) == 1
    merged = ledger.values()[0]
    assert merged.raw_content == "a much longer raw document"
    assert merged.metadata["queries"] == ["query one", "query two"]


def test_validator_finds_unknown_url_and_unsupported_critical_claim():
    known = evidence("https://sia.org/report")
    claim = Claim.create(
        "Global sales doubled",
        citations=[Citation(url="https://fabricated.invalid/report")],
    )
    result = CitationValidator().validate([claim], [known])
    codes = {issue.code for issue in result.issues}

    assert not result.valid
    assert "unknown_url" in codes
    assert "critical_claim_without_evidence" in codes
    assert result.critical_claim_coverage == 0.0


def test_validator_accepts_known_source_and_reports_duplicate_evidence():
    first = evidence("https://sia.org/report")
    duplicate = evidence("https://sia.org/report?utm_campaign=duplicate")
    claim = Claim.create("Sales increased", citations=[Citation(source_id=first.source_id)])
    result = CitationValidator().validate([claim], [first, duplicate])

    assert result.valid  # duplicate source is a warning, not a fabricated claim
    assert result.supported_critical_claims == 1
    assert any(issue.code == "duplicate_source" for issue in result.issues)


def test_validator_rejects_hallucinated_markdown_links():
    known = evidence("https://example.com/known")
    issues = CitationValidator().validate_report_urls(
        "[known](https://example.com/known) and [fake](https://fake.invalid/a)",
        [known],
    )
    assert [issue.url for issue in issues] == ["https://fake.invalid/a"]


def test_validator_extracts_structured_claims_from_report():
    claims = CitationValidator().extract_claims(
        "# Report\n\nSales increased according to [SIA](https://sia.org/report)."
    )

    assert len(claims) == 1
    assert claims[0].text == "Sales increased according to SIA."
    assert claims[0].citations[0].url == "https://sia.org/report"


def test_plain_source_basis_is_linked_to_collected_evidence():
    source = evidence(
        "https://www.12371.cn/2026/01/15/ARTI-example/",
        title="全国组织部长会议专题",
    )
    report = """## 干部队伍建设

来源依据：
- 共产党员网：全国组织部长会议专题
"""

    linked = ensure_clickable_sources(report, [source])

    assert (
        "- [共产党员网：全国组织部长会议专题]"
        "(https://www.12371.cn/2026/01/15/ARTI-example)"
    ) in linked


def test_inline_policy_basis_is_linked_in_place():
    source = evidence(
        "https://www.gov.cn/example/propaganda-meeting",
        title="全国宣传部长会议在京召开 蔡奇出席并讲话",
    )
    report = "**政策依据：** 2026年全国宣传部长会议"

    linked = ensure_clickable_sources(report, [source])

    assert linked == (
        "**政策依据：** "
        "[2026年全国宣传部长会议]"
        "(https://www.gov.cn/example/propaganda-meeting)"
    )


def test_unmentioned_evidence_is_not_appended_to_report_end():
    source = evidence("https://example.com/report", title="权威报告")

    linked = ensure_clickable_sources("# 研究报告\n\n正文。", [source])

    assert linked == "# 研究报告\n\n正文。"


def test_duplicate_trailing_reference_section_is_removed_after_inline_linking():
    source = evidence(
        "https://www.gov.cn/example/propaganda-meeting",
        title="全国宣传部长会议在京召开",
    )
    report = """# 研究报告

**政策依据：** 2026年全国宣传部长会议

## 参考文献

- [全国宣传部长会议在京召开](https://www.gov.cn/example/propaganda-meeting)
"""

    linked = ensure_clickable_sources(report, [source])

    assert "**政策依据：** [2026年全国宣传部长会议]" in linked
    assert "## 参考文献" not in linked


def test_search_policy_deduplicates_queries_and_urls_globally():
    policy = SearchQualityPolicy()
    assert policy.deduplicate_queries(["  A 股 半导体 ", "a 股   半导体", "SIA sales"]) == [
        "  A 股 半导体 ",
        "SIA sales",
    ]
    assert policy.accept_url("https://example.com/a?utm_source=x")
    assert not policy.accept_url("https://EXAMPLE.com/a/")


def test_search_policy_scores_authority_and_freshness():
    policy = SearchQualityPolicy()
    official = evidence(
        "https://www.gov.cn/policy",
        source_type="web",
        published_at="2026-07-01",
    )
    old_blog = evidence(
        "https://blog.example/post",
        source_type="blog",
        published_at="2019-01-01",
    )

    assert policy.score(official, now=date(2026, 7, 19)) > policy.score(
        old_blog, now=date(2026, 7, 19)
    )
    assert official.authority_score == 1.0
    assert official.freshness_score == 1.0


def test_cache_key_is_stable_across_whitespace_and_option_order():
    first = SearchQualityPolicy.cache_key(
        " SIA   Sales ", options={"max_results": 5, "topic": "news"}
    )
    second = SearchQualityPolicy.cache_key(
        "sia sales", options={"topic": "news", "max_results": 5}
    )
    assert first == second


def test_search_policy_checkpoint_round_trip():
    policy = SearchQualityPolicy()
    policy.accept_query("A股半导体")
    policy.accept_url("https://example.com/report")
    restored = SearchQualityPolicy.from_dict(json.loads(json.dumps(policy.to_dict())))

    assert not restored.accept_query("A股半导体")
    assert not restored.accept_url("https://example.com/report")
