"""Export a completed DeepResearch report as Markdown or a styled PDF."""
from __future__ import annotations

import html
import io
import os
import re
from datetime import datetime
from pathlib import Path


def render_markdown(title: str, content: str) -> bytes:
    body = (content or "").strip()
    if not body.startswith("#"):
        body = f"# {title.strip() or 'Deep Research'}\n\n{body}"
    return (body.rstrip() + "\n").encode("utf-8")


def render_pdf(title: str, content: str) -> bytes:
    """Render Markdown into an A4 PDF with Chinese font and page numbers."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    font_name = _register_pdf_font(pdfmetrics, UnicodeCIDFont, TTFont)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
        title=title or "Deep Research",
        author="知研 Agent DeepResearch",
    )
    styles = {
        "title": ParagraphStyle(
            "DRTitle", fontName=font_name, fontSize=22, leading=30,
            textColor=colors.HexColor("#0F172A"), alignment=TA_CENTER,
            spaceAfter=10 * mm,
        ),
        "h1": ParagraphStyle(
            "DRH1", fontName=font_name, fontSize=16, leading=22,
            textColor=colors.HexColor("#0E7490"), spaceBefore=6 * mm,
            spaceAfter=3 * mm,
        ),
        "h2": ParagraphStyle(
            "DRH2", fontName=font_name, fontSize=13, leading=19,
            textColor=colors.HexColor("#155E75"), spaceBefore=5 * mm,
            spaceAfter=2 * mm,
        ),
        "h3": ParagraphStyle(
            "DRH3", fontName=font_name, fontSize=11, leading=17,
            textColor=colors.HexColor("#334155"), spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        ),
        "h4": ParagraphStyle(
            "DRH4", fontName=font_name, fontSize=10.5, leading=16,
            textColor=colors.HexColor("#334155"), spaceBefore=3.5 * mm,
            spaceAfter=1.5 * mm,
        ),
        "h5": ParagraphStyle(
            "DRH5", fontName=font_name, fontSize=10, leading=15,
            textColor=colors.HexColor("#475569"), spaceBefore=3 * mm,
            spaceAfter=1.5 * mm,
        ),
        "h6": ParagraphStyle(
            "DRH6", fontName=font_name, fontSize=9.5, leading=15,
            textColor=colors.HexColor("#475569"), spaceBefore=2.5 * mm,
            spaceAfter=1 * mm,
        ),
        "body": ParagraphStyle(
            "DRBody", fontName=font_name, fontSize=9.5, leading=16,
            textColor=colors.HexColor("#1E293B"), alignment=TA_LEFT,
            spaceAfter=2.5 * mm, splitLongWords=True,
        ),
        "bullet": ParagraphStyle(
            "DRBullet", fontName=font_name, fontSize=9.5, leading=16,
            textColor=colors.HexColor("#1E293B"), leftIndent=6 * mm,
            firstLineIndent=-4 * mm, spaceAfter=1.5 * mm,
        ),
        "quote": ParagraphStyle(
            "DRQuote", fontName=font_name, fontSize=9, leading=15,
            textColor=colors.HexColor("#475569"), leftIndent=7 * mm,
            borderColor=colors.HexColor("#67E8F9"), borderWidth=1,
            borderPadding=(2 * mm, 3 * mm, 2 * mm, 3 * mm),
            backColor=colors.HexColor("#ECFEFF"), spaceAfter=3 * mm,
        ),
        "code": ParagraphStyle(
            "DRCode", fontName=font_name, fontSize=8, leading=12,
            textColor=colors.HexColor("#E2E8F0"), backColor=colors.HexColor("#0F172A"),
            borderPadding=3 * mm, leftIndent=2 * mm, rightIndent=2 * mm,
            spaceBefore=2 * mm, spaceAfter=3 * mm,
        ),
        "table": ParagraphStyle(
            "DRTable", fontName=font_name, fontSize=7.5, leading=10,
            textColor=colors.HexColor("#1E293B"),
        ),
        "meta": ParagraphStyle(
            "DRMeta", fontName=font_name, fontSize=8.5, leading=13,
            textColor=colors.HexColor("#64748B"), alignment=TA_CENTER,
            spaceAfter=8 * mm,
        ),
    }

    story = [
        Paragraph(_inline(title.strip() or "Deep Research"), styles["title"]),
        Paragraph(
            f"知研 Agent DeepResearch · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            styles["meta"],
        ),
    ]
    story.extend(_markdown_flowables(content, styles, doc.width, title))

    def footer(canvas, document) -> None:
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(20 * mm, 10 * mm, "知研 Agent · DeepResearch")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"第 {document.page} 页")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def _markdown_flowables(
    markdown: str,
    styles: dict,
    width: float,
    document_title: str = "",
) -> list:
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle

    lines = (markdown or "").replace("\r\n", "\n").splitlines()
    flowables: list = []
    paragraph: list[str] = []
    in_code = False
    code_lines: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            flowables.append(Paragraph(_inline(" ".join(paragraph)), styles["body"]))
            paragraph.clear()

    while index < len(lines):
        raw = lines[index]
        line = raw.strip()
        if line.startswith("```"):
            flush_paragraph()
            if in_code:
                flowables.append(Paragraph("<br/>".join(html.escape(x) for x in code_lines), styles["code"]))
                code_lines.clear()
            in_code = not in_code
            index += 1
            continue
        if in_code:
            code_lines.append(raw)
            index += 1
            continue
        if not line:
            flush_paragraph()
            index += 1
            continue
        if line == "---":
            flush_paragraph()
            flowables.append(Spacer(1, 3 * mm))
            index += 1
            continue
        if line == "<!-- pagebreak -->":
            flush_paragraph()
            flowables.append(PageBreak())
            index += 1
            continue
        if line.startswith("|") and index + 1 < len(lines) and _is_table_separator(lines[index + 1]):
            flush_paragraph()
            table_lines = [line]
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            rows = [_table_cells(row) for row in table_lines]
            columns = max(len(row) for row in rows)
            rows = [row + [""] * (columns - len(row)) for row in rows]
            data = [[Paragraph(_inline(cell), styles["table"]) for cell in row] for row in rows]
            table = Table(data, colWidths=[width / columns] * columns, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#CFFAFE")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#155E75")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            flowables.extend([table, Spacer(1, 3 * mm)])
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            if (
                len(heading.group(1)) == 1
                and not flowables
                and heading.group(2).strip() == document_title.strip()
            ):
                index += 1
                continue
            flowables.append(Paragraph(_inline(heading.group(2)), styles[f"h{len(heading.group(1))}"]))
            index += 1
            continue
        unordered_item = re.match(r"^[-*+]\s+(.+)$", line)
        ordered_item = re.match(r"^(\d+)[.)]\s+(.+)$", line)
        if unordered_item or ordered_item:
            flush_paragraph()
            item_text = (
                unordered_item.group(1)
                if unordered_item
                else ordered_item.group(2)
            )
            bullet_text = "•" if unordered_item else f"{ordered_item.group(1)}."
            flowables.append(
                Paragraph(
                    _inline(item_text),
                    styles["bullet"],
                    bulletText=bullet_text,
                )
            )
            index += 1
            continue
        if line.startswith(">"):
            flush_paragraph()
            flowables.append(Paragraph(_inline(line.lstrip("> ")), styles["quote"]))
            index += 1
            continue
        paragraph.append(line)
        index += 1

    flush_paragraph()
    if code_lines:
        flowables.append(Paragraph("<br/>".join(html.escape(x) for x in code_lines), styles["code"]))
    return flowables


def _inline(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text or "")
    links: list[str] = []

    def stash_link(match: re.Match[str]) -> str:
        token = f"DRLINKTOKEN{len(links)}END"
        label = _inline_text(match.group(1))
        url = html.escape(match.group(2), quote=True)
        links.append(f'<link href="{url}" color="#0891B2"><u>{label}</u></link>')
        return token

    rendered = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        stash_link,
        text,
    )
    rendered = _inline_text(rendered)
    for index, link in enumerate(links):
        rendered = rendered.replace(f"DRLINKTOKEN{index}END", link)
    return rendered.replace("\n", "<br/>")


def _inline_text(text: str) -> str:
    """Convert supported inline Markdown without touching generated link HTML."""
    code_spans: list[str] = []

    def stash_code(match: re.Match[str]) -> str:
        token = f"DRCODETOKEN{len(code_spans)}END"
        code_spans.append(html.escape(match.group(1)))
        return token

    rendered = re.sub(r"`([^`\n]+)`", stash_code, text)
    rendered = html.escape(rendered)
    rendered = re.sub(
        r"\*\*\*([^*\n]+)\*\*\*",
        r"<b><i>\1</i></b>",
        rendered,
    )
    rendered = re.sub(
        r"___([^_\n]+)___",
        r"<b><i>\1</i></b>",
        rendered,
    )
    rendered = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", rendered)
    rendered = re.sub(
        r"(?<!_)__([^_\n]+)__(?!_)",
        r"<b>\1</b>",
        rendered,
    )
    rendered = re.sub(
        r"(?<!\*)\*([^*\n]+)\*(?!\*)",
        r"<i>\1</i>",
        rendered,
    )
    rendered = re.sub(
        r"(?<!_)_([^_\n]+)_(?!_)",
        r"<i>\1</i>",
        rendered,
    )
    rendered = re.sub(r"~~([^~\n]+)~~", r"<strike>\1</strike>", rendered)
    for index, code in enumerate(code_spans):
        rendered = rendered.replace(
            f"DRCODETOKEN{index}END",
            f'<font color="#0E7490">{code}</font>',
        )
    return rendered


def _is_table_separator(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _register_pdf_font(pdfmetrics, UnicodeCIDFont, TTFont) -> str:
    """Prefer an embedded CJK font; fall back to the standard CID font."""
    candidates = [
        os.environ.get("DEEP_RESEARCH_PDF_FONT", ""),
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            name = "DeepResearchCJK"
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, candidate, subfontIndex=0))
            return name
    fallback = "STSong-Light"
    if fallback not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(fallback))
    return fallback


__all__ = ["render_markdown", "render_pdf"]
