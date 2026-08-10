"""Render a focused Multi-Agent DeepResearch architecture diagram."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).with_name("deepresearch-agent-architecture.png")
REGULAR = r"C:\Windows\Fonts\msyh.ttc"
BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

W, H = 2400, 1500
BG = "#F8FAFC"
TEXT = "#0F172A"
MUTED = "#475569"
LINE = "#64748B"
BLUE = "#2563EB"
BLUE_BG = "#EFF6FF"
CYAN = "#0891B2"
CYAN_BG = "#ECFEFF"
GREEN = "#059669"
GREEN_BG = "#ECFDF5"
ORANGE = "#EA580C"
ORANGE_BG = "#FFF7ED"
RED = "#DC2626"
RED_BG = "#FEF2F2"
VIOLET = "#7C3AED"
VIOLET_BG = "#F5F3FF"
WHITE = "#FFFFFF"


img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)


def ft(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(BOLD if bold else REGULAR, size)


def text_center(rect, value, size=24, color=TEXT, bold=False, spacing=7):
    x1, y1, x2, y2 = rect
    f = ft(size, bold)
    bb = d.multiline_textbbox((0, 0), value, font=f, spacing=spacing, align="center")
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.multiline_text(
        ((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - bb[1]),
        value,
        font=f,
        fill=color,
        spacing=spacing,
        align="center",
    )


def box(rect, value, *, fill=WHITE, outline=LINE, width=2, radius=18, size=23, bold=False, color=TEXT):
    d.rounded_rectangle(rect, radius=radius, fill=fill, outline=outline, width=width)
    text_center(rect, value, size=size, color=color, bold=bold)


def arrow(points, *, color=LINE, width=4, head=15):
    d.line(points, fill=color, width=width, joint="curve")
    (x0, y0), (x1, y1) = points[-2], points[-1]
    a = math.atan2(y1 - y0, x1 - x0)
    spread = 0.62
    left = (x1 - head * math.cos(a - spread), y1 - head * math.sin(a - spread))
    right = (x1 - head * math.cos(a + spread), y1 - head * math.sin(a + spread))
    d.polygon([(x1, y1), left, right], fill=color)


def dashed(points, *, color=LINE, width=3):
    for p0, p1 in zip(points, points[1:]):
        x0, y0 = p0
        x1, y1 = p1
        length = max(1, int(math.hypot(x1 - x0, y1 - y0)))
        for offset in range(0, length, 18):
            end = min(offset + 10, length)
            d.line(
                (
                    x0 + (x1 - x0) * offset / length,
                    y0 + (y1 - y0) * offset / length,
                    x0 + (x1 - x0) * end / length,
                    y0 + (y1 - y0) * end / length,
                ),
                fill=color,
                width=width,
            )


def swimlane(y1, y2, title, number, color, fill):
    d.rounded_rectangle((55, y1, 2345, y2), radius=22, fill=fill, outline=color, width=2)
    d.rounded_rectangle((75, y1 + 18, 310, y2 - 18), radius=18, fill=color)
    text_center((75, y1 + 18, 310, y2 - 18), f"{number}\n{title}", size=26, color=WHITE, bold=True)


# Title
text_center((0, 18, W, 82), "Multi-Agent DeepResearch 架构", size=55, bold=True)
text_center(
    (0, 80, W, 122),
    "规划 → 并行研究 → 证据合并 → 对抗评估 → Replan / Finalize",
    size=28,
    color=BLUE,
    bold=True,
)

# Lanes
swimlane(145, 300, "初始化", "①", BLUE, "#F8FBFF")
swimlane(330, 510, "主控决策", "②", CYAN, "#F4FDFF")
swimlane(540, 775, "并行研究", "③", GREEN, "#F5FDF9")
swimlane(805, 1045, "对抗质检", "④", ORANGE, "#FFFBF5")
swimlane(1075, 1235, "最终交付", "⑤", VIOLET, "#FAF8FF")

# 1. Initialization
init = [
    ((350, 185, 620, 260), "用户研究问题", BLUE, BLUE_BG),
    ((690, 175, 1045, 270), "Context Builder\nMemory + Skills + Lessons", VIOLET, VIOLET_BG),
    ((1115, 175, 1395, 270), "BriefWriter\n子 Agent", BLUE, BLUE_BG),
    ((1465, 175, 1745, 270), "DraftWriter\n子 Agent", BLUE, BLUE_BG),
    ((1815, 175, 2260, 270), "ResearchState 初始化\nBrief / Draft / Budget", CYAN, CYAN_BG),
]
for rect, label, color, fill in init:
    box(rect, label, fill=fill, outline=color, width=3, size=22, bold=True)
for left, right in zip(init, init[1:]):
    arrow([(left[0][2], (left[0][1] + left[0][3]) // 2), (right[0][0], (right[0][1] + right[0][3]) // 2)], color=BLUE)

# 2. Supervisor controller
box(
    (610, 365, 1780, 475),
    "Supervisor · 主 Agent\n读取 State，选择下一步动作，不直接执行搜索",
    fill="#CFFAFE",
    outline=CYAN,
    width=4,
    size=28,
    bold=True,
)
actions = [
    ((1835, 355, 2255, 398), "ConductResearch", GREEN, GREEN_BG),
    ((1835, 410, 2255, 453), "RefineDraft / Think", ORANGE, ORANGE_BG),
    ((1835, 465, 2255, 498), "Finish", VIOLET, VIOLET_BG),
]
for rect, label, color, fill in actions:
    box(rect, label, fill=fill, outline=color, size=18, bold=True, radius=13)
arrow([(2035, 270), (2035, 310), (1195, 310), (1195, 365)], color=CYAN)

# 3. Research lane
box((350, 575, 650, 735), "SubResearcher\n子 Agent 池\nAgent 1 / Agent 2 / Agent N", fill=GREEN_BG, outline=GREEN, width=3, size=20, bold=True)
box((735, 605, 1035, 705), "统一 ToolRuntime\n非 Agent 基础设施\n协议 / 超时 / 取消", fill=WHITE, outline=GREEN, width=3, size=18, bold=True)
box((1120, 605, 1420, 705), "Search Tools\nTavily / Knowledge Base", fill=WHITE, outline=GREEN, width=3, size=20, bold=True)
box((1505, 605, 1805, 705), "Evidence Ledger\nURL 全局去重与排序", fill=GREEN_BG, outline=GREEN, width=3, size=20, bold=True)
box((1890, 595, 2260, 715), "Compressed Research Notes\n只回传摘要与 Evidence ID", fill=GREEN_BG, outline=GREEN, width=3, size=19, bold=True)
arrow([(2035, 398), (2295, 398), (2295, 565), (500, 565), (500, 585)], color=GREEN)
arrow([(650, 655), (735, 655)], color=GREEN)
arrow([(1035, 655), (1120, 655)], color=GREEN)
arrow([(1420, 655), (1505, 655)], color=GREEN)
arrow([(1805, 655), (1890, 655)], color=GREEN)
arrow([(2075, 595), (2075, 525), (1500, 525), (1500, 475)], color=GREEN)
text_center((1870, 515, 2265, 555), "新增证据回到 Supervisor", size=18, color=GREEN, bold=True)

# 4. Quality lane
quality = [
    ((350, 870, 650, 965), "增量修订 Draft", ORANGE, ORANGE_BG),
    ((730, 850, 1030, 985), "Red Team\n子 Agent\n事实 / 引用 / 逻辑 / 覆盖", RED, RED_BG),
    ((1110, 870, 1410, 965), "Critique Lifecycle\nOpen → Resolve / Reject", RED, RED_BG),
    ((1490, 850, 1790, 985), "Evaluator\n子 Agent · LLM-as-Judge\n全面性 / 准确性 / 一致性", ORANGE, ORANGE_BG),
    ((1870, 850, 2260, 985), "Adaptive StopPolicy\n非 Agent 策略组件\n质量 / 覆盖 / 增量 / 预算", ORANGE, ORANGE_BG),
]
for rect, label, color, fill in quality:
    box(rect, label, fill=fill, outline=color, width=3, size=20, bold=True)
arrow([(1835, 432), (1810, 432), (1810, 315), (320, 315), (320, 918), (350, 918)], color=ORANGE)
for left, right in zip(quality, quality[1:]):
    arrow([(left[0][2], (left[0][1] + left[0][3]) // 2), (right[0][0], (right[0][1] + right[0][3]) // 2)], color=ORANGE if left[2] != RED else RED)

# Replan loop and finish branch
arrow([(2065, 850), (2065, 790), (2320, 790), (2320, 315), (1580, 315), (1580, 365)], color=BLUE, width=5)
box((1980, 790, 2260, 830), "继续研究 / Replan", fill=BLUE_BG, outline=BLUE, size=17, bold=True, radius=12)

# 5. Delivery lane
delivery = [
    ((610, 1105, 920, 1205), "FinalWriter\n子 Agent", VIOLET, VIOLET_BG),
    ((1010, 1105, 1350, 1205), "Citation Validator\n非 Agent 校验组件\nClaim - Evidence 对齐", GREEN, GREEN_BG),
    ((1440, 1115, 1750, 1195), "研究历史持久化", BLUE, BLUE_BG),
    ((1840, 1115, 2190, 1195), "Markdown / PDF\n连续追问", VIOLET, VIOLET_BG),
]
for rect, label, color, fill in delivery:
    box(rect, label, fill=fill, outline=color, width=3, size=21, bold=True)
arrow([(2065, 985), (2065, 1060), (765, 1060), (765, 1115)], color=VIOLET, width=5)
text_center((1710, 1022, 2080, 1062), "质量达标 / 强制终止", size=18, color=VIOLET, bold=True)
for left, right in zip(delivery, delivery[1:]):
    arrow([(left[0][2], (left[0][1] + left[0][3]) // 2), (right[0][0], (right[0][1] + right[0][3]) // 2)], color=VIOLET)

# Cross-cutting state and reliability
box(
    (80, 1280, 2320, 1360),
    "LangGraph ResearchState    ·    Brief / Draft / Evidence / Notes / Critiques / Evaluations / Usage / StopReason",
    fill=BLUE_BG,
    outline=BLUE,
    width=3,
    size=24,
    bold=True,
)
box(
    (80, 1385, 2320, 1465),
    "Long-Horizon 保障    ·    SQLite Checkpoint    ·    ToolRuntime 幂等协议    ·    Retry / Circuit / Cancel    ·    Token & Cost Budget    ·    SSE / LangFuse",
    fill=VIOLET_BG,
    outline=VIOLET,
    width=3,
    size=23,
    bold=True,
)

# Agent hierarchy legend
box((90, 90, 570, 126), "主 Agent：Supervisor", fill=CYAN_BG, outline=CYAN, size=17, bold=True, radius=12)
box(
    (1490, 90, 2310, 126),
    "子 Agent：Brief / Draft / SubResearch / Red Team / Evaluator / FinalWriter",
    fill=VIOLET_BG,
    outline=VIOLET,
    size=14,
    bold=True,
    radius=12,
)

img.save(OUT, quality=96)
print(OUT)
