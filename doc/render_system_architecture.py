"""Render the project architecture as a deterministic PNG infographic."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "system-architecture.png"
FONT_REGULAR = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

W, H = 2400, 1600
BG = "#F8FAFC"
TEXT = "#0F172A"
MUTED = "#475569"
LINE = "#64748B"
BLUE = "#2563EB"
BLUE_BG = "#EFF6FF"
CYAN = "#0891B2"
CYAN_BG = "#ECFEFF"
VIOLET = "#7C3AED"
VIOLET_BG = "#F5F3FF"
GREEN = "#059669"
GREEN_BG = "#ECFDF5"
ORANGE = "#EA580C"
ORANGE_BG = "#FFF7ED"
RED = "#DC2626"
RED_BG = "#FEF2F2"
WHITE = "#FFFFFF"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


canvas = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(canvas)


def center_text(
    rect: tuple[int, int, int, int],
    text: str,
    *,
    size: int = 26,
    color: str = TEXT,
    bold: bool = False,
    spacing: int = 8,
) -> None:
    x1, y1, x2, y2 = rect
    f = font(size, bold)
    bbox = draw.multiline_textbbox((0, 0), text, font=f, spacing=spacing, align="center")
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.multiline_text(
        ((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - bbox[1]),
        text,
        font=f,
        fill=color,
        spacing=spacing,
        align="center",
    )


def box(
    rect: tuple[int, int, int, int],
    text: str,
    *,
    fill: str = WHITE,
    outline: str = LINE,
    width: int = 2,
    radius: int = 18,
    size: int = 25,
    bold: bool = False,
    color: str = TEXT,
) -> None:
    draw.rounded_rectangle(rect, radius=radius, fill=fill, outline=outline, width=width)
    center_text(rect, text, size=size, bold=bold, color=color)


def arrow(points: list[tuple[int, int]], *, color: str = LINE, width: int = 4) -> None:
    draw.line(points, fill=color, width=width, joint="curve")
    (x0, y0), (x1, y1) = points[-2], points[-1]
    angle = math.atan2(y1 - y0, x1 - x0)
    length = 14
    spread = 0.62
    tip = (x1, y1)
    left = (
        x1 - length * math.cos(angle - spread),
        y1 - length * math.sin(angle - spread),
    )
    right = (
        x1 - length * math.cos(angle + spread),
        y1 - length * math.sin(angle + spread),
    )
    draw.polygon([tip, left, right], fill=color)


def dashed_line(points: list[tuple[int, int]], *, color: str, width: int = 3) -> None:
    for start, end in zip(points, points[1:]):
        x0, y0 = start
        x1, y1 = end
        dist = max(1, int(math.hypot(x1 - x0, y1 - y0)))
        for offset in range(0, dist, 18):
            end_offset = min(offset + 10, dist)
            sx = x0 + (x1 - x0) * offset / dist
            sy = y0 + (y1 - y0) * offset / dist
            ex = x0 + (x1 - x0) * end_offset / dist
            ey = y0 + (y1 - y0) * end_offset / dist
            draw.line((sx, sy, ex, ey), fill=color, width=width)


def lane(rect: tuple[int, int, int, int], title: str, color: str, fill: str) -> None:
    draw.rounded_rectangle(rect, radius=24, fill=fill, outline=color, width=3)
    x1, y1, x2, _ = rect
    draw.rounded_rectangle((x1 + 22, y1 - 24, x1 + 430, y1 + 42), radius=18, fill=color)
    center_text((x1 + 22, y1 - 24, x1 + 430, y1 + 42), title, size=30, bold=True, color=WHITE)


# Header
center_text((0, 18, W, 92), "智能 Agent 工作台 · 系统架构", size=58, bold=True)
center_text(
    (0, 82, W, 126),
    "RAG + Multi-Agent DeepResearch + Memory + Agent Skills",
    size=28,
    color=BLUE,
    bold=True,
)

# Frontend and gateway
box(
    (150, 145, 2250, 235),
    "React 前端工作台    ·    视频 / 笔记 / AI 对话 / 深度研究 / 统计",
    fill=BLUE_BG,
    outline=BLUE,
    width=3,
    size=30,
    bold=True,
)
arrow([(1200, 235), (1200, 270)], color=BLUE)
center_text((1260, 236, 1440, 270), "REST + SSE", size=20, color=BLUE, bold=True)
box(
    (150, 270, 2250, 350),
    "FastAPI 接入层    ·    API 路由    ·    SSE 流式输出    ·    Guardrails    ·    Cancel / Retry / Timeout",
    fill=WHITE,
    outline="#94A3B8",
    width=3,
    size=26,
    bold=True,
)

# Main lanes
rag_lane = (80, 405, 1150, 1070)
agent_lane = (1250, 405, 2320, 1070)
lane(rag_lane, "RAG 知识库问答", BLUE, "#F7FAFF")
lane(agent_lane, "Multi-Agent DeepResearch", CYAN, "#F5FEFF")
arrow([(760, 350), (760, 405)], color=BLUE)
arrow([(1640, 350), (1640, 405)], color=CYAN)

# RAG ingestion branch
box((120, 470, 400, 545), "视频字幕 / 本地笔记", fill=VIOLET_BG, outline=VIOLET, size=22, bold=True)
box((455, 470, 710, 545), "分块 + Embedding", fill=VIOLET_BG, outline=VIOLET, size=22, bold=True)
box((765, 470, 1085, 545), "ChromaDB + BM25", fill=BLUE_BG, outline=BLUE, size=23, bold=True)
arrow([(400, 508), (455, 508)], color=VIOLET)
arrow([(710, 508), (765, 508)], color=VIOLET)

# RAG query flow
rag_boxes = [
    ((120, 600, 390, 680), "用户 Query"),
    ((440, 600, 745, 680), "意图识别\n+ Query Rewrite"),
    ((795, 600, 1085, 680), "Multi-Query"),
    ((120, 745, 390, 825), "ChromaDB\n+ BM25"),
    ((440, 745, 745, 825), "RRF 融合\n+ 全局去重"),
    ((795, 745, 1085, 825), "CrossEncoder\n精排"),
    ((270, 890, 590, 970), "Reflection\n补充检索"),
    ((650, 890, 970, 970), "带引用回答"),
]
for rect, label in rag_boxes:
    box(rect, label, fill=WHITE, outline=BLUE, size=23, bold=True)
arrow([(390, 640), (440, 640)], color=BLUE)
arrow([(745, 640), (795, 640)], color=BLUE)
arrow([(940, 680), (940, 710), (255, 710), (255, 745)], color=BLUE)
arrow([(390, 785), (440, 785)], color=BLUE)
arrow([(745, 785), (795, 785)], color=BLUE)
arrow([(940, 825), (940, 855), (430, 855), (430, 890)], color=BLUE)
arrow([(590, 930), (650, 930)], color=BLUE)
arrow([(925, 545), (925, 575), (255, 575), (255, 600)], color=VIOLET, width=3)

# Agent top flow
box((1295, 470, 1535, 545), "BriefWriter", fill=CYAN_BG, outline=CYAN, size=22, bold=True)
box((1580, 470, 1820, 545), "DraftWriter", fill=CYAN_BG, outline=CYAN, size=22, bold=True)
box((1865, 460, 2265, 555), "Supervisor · 主 Agent", fill="#CFFAFE", outline=CYAN, width=4, size=27, bold=True)
arrow([(1535, 508), (1580, 508)], color=CYAN)
arrow([(1820, 508), (1865, 508)], color=CYAN)

# Research loop
box((1295, 620, 1555, 700), "并行\nSubResearcher", fill=WHITE, outline=CYAN, size=21, bold=True)
box((1590, 620, 1835, 700), "统一\nToolRuntime", fill=WHITE, outline=CYAN, size=21, bold=True)
box((1870, 620, 2265, 700), "Tavily / 知识库搜索", fill=WHITE, outline=CYAN, size=22, bold=True)
arrow([(2065, 555), (2065, 585), (1425, 585), (1425, 620)], color=CYAN)
arrow([(1555, 660), (1590, 660)], color=CYAN)
arrow([(1835, 660), (1870, 660)], color=CYAN)

box((1295, 750, 1580, 830), "Evidence Ledger", fill=GREEN_BG, outline=GREEN, size=22, bold=True)
box((1630, 750, 1990, 830), "Compressed\nResearch Notes", fill=GREEN_BG, outline=GREEN, size=21, bold=True)
arrow([(2065, 700), (2065, 725), (1438, 725), (1438, 750)], color=GREEN)
arrow([(1580, 790), (1630, 790)], color=GREEN)
arrow([(1990, 790), (2205, 790), (2205, 555)], color=GREEN)

# Quality loop
box((1295, 900, 1515, 975), "Red Team", fill=RED_BG, outline=RED, size=22, bold=True)
box((1555, 900, 1845, 975), "LLM-as-Judge\nEvaluator", fill=ORANGE_BG, outline=ORANGE, size=20, bold=True)
box((1885, 890, 2265, 985), "Adaptive StopPolicy", fill=ORANGE_BG, outline=ORANGE, size=22, bold=True)
arrow([(2065, 830), (2065, 860), (1405, 860), (1405, 900)], color=RED)
arrow([(1515, 938), (1555, 938)], color=ORANGE)
arrow([(1845, 938), (1885, 938)], color=ORANGE)

box((1300, 1005, 1520, 1050), "继续 / Replan", fill=BLUE_BG, outline=BLUE, size=19, bold=True)
box((1570, 1005, 1750, 1050), "FinalWriter", fill=GREEN_BG, outline=GREEN, size=18, bold=True)
box((1795, 1005, 2030, 1050), "Citation Validator", fill=GREEN_BG, outline=GREEN, size=17, bold=True)
box((2075, 1005, 2265, 1050), "MD / PDF", fill=GREEN_BG, outline=GREEN, size=18, bold=True)
arrow([(2075, 985), (2075, 995), (1410, 995), (1410, 1005)], color=BLUE, width=3)
arrow([(1410, 1005), (1410, 575), (1950, 575), (1950, 555)], color=BLUE, width=3)
arrow([(2075, 985), (2075, 995), (1660, 995), (1660, 1005)], color=GREEN, width=3)
arrow([(1750, 1028), (1795, 1028)], color=GREEN, width=3)
arrow([(2030, 1028), (2075, 1028)], color=GREEN, width=3)

# Cross-cutting layers
box(
    (100, 1110, 2300, 1200),
    "Long-Horizon 基础设施    ·    LangGraph 类型化状态    ·    SQLite Checkpoint    ·    Token / Cost Budget    ·    可观测性",
    fill=VIOLET_BG,
    outline=VIOLET,
    width=3,
    size=25,
    bold=True,
)
box(
    (100, 1230, 2300, 1335),
    "Memory & Self-Evolution    ·    Observation → Profile / Semantic / Episodic / Procedural\nReflection / Conflict / Supersede / Forgetting    ·    Agent Skills / LessonStore",
    fill=GREEN_BG,
    outline=GREEN,
    width=3,
    size=24,
    bold=True,
)
dashed_line([(600, 1230), (600, 1070)], color=GREEN)
dashed_line([(1830, 1230), (1830, 1070)], color=GREEN)

# Storage and external services
bottom = [
    ((100, 1380, 600, 1535), "MySQL\n用户 / 对话 / 研究历史\nEvidence / Citation", BLUE, BLUE_BG),
    ((635, 1380, 1010, 1535), "ChromaDB + BM25", VIOLET, VIOLET_BG),
    ((1045, 1380, 1420, 1535), "Obsidian / Markdown", CYAN, CYAN_BG),
    ((1455, 1380, 1815, 1535), "SQLite Checkpoint", ORANGE, ORANGE_BG),
    ((1850, 1380, 2300, 1535), "外部服务\nDeepSeek V4 Flash / Pro\nTavily / Whisper / LangFuse", GREEN, GREEN_BG),
]
for rect, label, color, fill in bottom:
    box(rect, label, fill=fill, outline=color, width=3, size=22, bold=True)

canvas.save(OUTPUT, quality=95)
print(OUTPUT)

