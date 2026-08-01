from __future__ import annotations

import io

from pypdf import PdfReader

from agents.deep_research.report_export import (
    _inline,
    _markdown_flowables,
    render_markdown,
    render_pdf,
)


SAMPLE = """# 2026 年半导体趋势

## 核心结论

- 需求侧由 **AI 算力** 驱动。
- 风险来自库存与出口限制。

| 指标 | 趋势 | 证据 |
| --- | --- | --- |
| 销售额 | 上升 | [SIA](https://www.semiconductors.org/) |

> 所有结论都应回到本次 Research Run 的 Evidence。
"""

MARKDOWN_VARIANTS = """#### 3.1.6 基金经理投资策略

*来源：易方达基金官网、[蛋卷基金](https://danjuanapp.com/)*

- 历史实际收益率计算
- 未来收益率区间构建

1. 乐观情景
2. 中性情景
"""


def test_markdown_export_preserves_existing_title():
    payload = render_markdown("ignored", SAMPLE)

    assert payload.startswith("# 2026 年半导体趋势".encode("utf-8"))
    assert payload.endswith(b"\n")


def test_pdf_export_is_readable_and_paginated():
    payload = render_pdf("2026 年半导体趋势", SAMPLE)
    reader = PdfReader(io.BytesIO(payload))

    assert payload.startswith(b"%PDF-")
    assert len(reader.pages) == 1
    assert reader.metadata.title == "2026 年半导体趋势"


def test_pdf_export_consumes_h4_italic_and_list_markers():
    payload = render_pdf("基金研究", MARKDOWN_VARIANTS)
    reader = PdfReader(io.BytesIO(payload))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "3.1.6 基金经理投资策略" in extracted
    assert "来源：易方达基金官网" in extracted
    assert "历史实际收益率计算" in extracted
    assert "####" not in extracted
    assert "*来源" not in extracted
    assert "- 历史实际收益率计算" not in extracted


def test_inline_markdown_converts_emphasis():
    rendered = _inline("*来源*与_口径_，以及***重要结论***")

    assert rendered == (
        "<i>来源</i>与<i>口径</i>，以及<b><i>重要结论</i></b>"
    )


def test_markdown_bullets_use_pdf_bullet_metadata():
    from reportlab.lib.styles import getSampleStyleSheet

    normal = getSampleStyleSheet()["BodyText"]
    flowables = _markdown_flowables(
        "- 历史实际收益率计算",
        {"body": normal, "bullet": normal},
        400,
    )

    assert flowables[0].bulletText == "•"
    assert flowables[0].getPlainText() == "历史实际收益率计算"
