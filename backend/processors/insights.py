import json
import re

from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, MAX_TRANSCRIPT_CHARS

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

CATEGORIES = [
    "财经理财", "AI与科技", "心理学", "商业创业", "健康生活",
    "教育学习", "历史文化", "娱乐综艺", "科学探索", "其他",
]

_TRANSLATE_CHUNK = 3000

# ── Step 1: Analysis ──────────────────────────────────────────────────────────

_ANALYZE_SYSTEM = (
    "你是一个知识分析专家。分析视频内容与已有知识库的关联，"
    "所有文本字段使用简体中文，"
    "输出严格 JSON（不要 markdown 代码块，不要任何额外解释）。"
)

_ANALYZE_PROMPT = """\
{purpose_context}请分析以下视频内容，并与知识库中已有的内容建立关联。

**视频标题**：{title}
**频道**：{channel}
**知识库中已有条目**（标题列表）：
{existing_titles}

**字幕内容**（前6000字）：
{transcript}

---
输出以下 JSON 结构：
{{
  "core_entities": ["核心实体或概念1", "核心实体或概念2"],
  "related_existing": ["与已有条目标题精确匹配的标题1", "标题2"],
  "new_concepts": ["知识库中尚未涉及的新概念1", "新概念2"],
  "contradictions": ["与已有知识相矛盾的观点（可为空列表）"],
  "knowledge_gaps": ["需要进一步研究才能理解此内容的空白1"],
  "connection_summary": "一段话描述此视频与已有知识的整体关联"
}}"""

# ── Step 2: Wiki page generation ──────────────────────────────────────────────

_WIKI_SYSTEM = (
    "你是一个知识工程师。基于分析结果，生成结构化的 Wiki 知识页面，"
    "用简体中文输出，Markdown 格式。对知识库中已有条目使用 [[条目标题]] 格式引用。"
)

_WIKI_PROMPT = """\
{purpose_context}请基于以下分析结果，为视频生成结构化的 Wiki 知识页面。
已有知识库条目请用 [[条目标题]] 格式引用，矛盾观点请在知识关联部分标注。

**视频标题**：{title}
**频道**：{channel}
**链接**：{url}

**分析结果**：
{analysis_summary}

**字幕内容**：
{transcript}

---
请输出以下结构（严格使用此 Markdown 格式，不要改变标题文字）：

## 分类
（从以下选项中选择最匹配的一个，只输出分类名称，不加任何解释：财经理财 / AI与科技 / 心理学 / 商业创业 / 健康生活 / 教育学习 / 历史文化 / 娱乐综艺 / 科学探索 / 其他）

## 核心摘要
（2-3句话概括视频核心内容）

## 主要观点
（列出 3-7 个核心观点，每个用 **加粗标题** + 一段说明）

## 关键概念
（列出重要术语/概念，格式：`概念名` - 简短解释。已有条目使用 [[条目名]] 格式）

## 知识关联
（与知识库中已有内容的关联，使用 [[条目名]] 引用，说明关联原因；若有矛盾观点也在此标注）

## 行动启示
（可以立即应用的建议或思维方式）

## 标签
（5-8个相关标签，格式：#标签1 #标签2 ...）"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_mainly_chinese(text: str) -> bool:
    sample = text[:3000]
    if not sample:
        return True
    chinese = sum(1 for c in sample if '一' <= c <= '鿿')
    return chinese / len(sample) > 0.12


def translate_to_chinese(text: str) -> str:
    chunks = [text[i:i + _TRANSLATE_CHUNK] for i in range(0, len(text), _TRANSLATE_CHUNK)]
    parts = []
    for chunk in chunks:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            max_tokens=4096,
            messages=[
                {
                    "role": "system",
                    "content": "你是专业翻译。将以下内容翻译成简体中文，保持原意和段落结构，只输出译文，不要任何解释。",
                },
                {"role": "user", "content": chunk},
            ],
        )
        parts.append(resp.choices[0].message.content or chunk)
    return "\n\n".join(parts)


def _get_existing_titles() -> list[str]:
    try:
        from storage.video_db import list_videos
        from storage.notes_db import list_notes
        titles = [v.get("title", "") for v in list_videos()] + [n.get("title", "") for n in list_notes()]
        return [t for t in titles if t]
    except Exception:
        return []


def _analyze_transcript(transcript: str, metadata: dict, existing_titles: list[str], purpose_context: str) -> dict:
    titles_text = "\n".join(f"- {t}" for t in existing_titles[:40]) if existing_titles else "（知识库暂无内容）"
    try:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            max_tokens=800,
            messages=[
                {"role": "system", "content": _ANALYZE_SYSTEM},
                {
                    "role": "user",
                    "content": _ANALYZE_PROMPT.format(
                        purpose_context=purpose_context,
                        title=metadata.get("title", "未知"),
                        channel=metadata.get("channel", "未知"),
                        existing_titles=titles_text,
                        transcript=transcript[:6000],
                    ),
                },
            ],
        )
        raw = resp.choices[0].message.content or "{}"
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(match.group()) if match else {}
    except Exception:
        return {}


def _format_analysis_summary(analysis: dict) -> str:
    parts = []
    if analysis.get("connection_summary"):
        parts.append(f"**整体关联**：{analysis['connection_summary']}")
    if analysis.get("related_existing"):
        parts.append("**关联已有内容**：" + "、".join(f"[[{t}]]" for t in analysis["related_existing"][:6]))
    if analysis.get("new_concepts"):
        parts.append("**新概念**：" + "、".join(analysis["new_concepts"][:5]))
    if analysis.get("contradictions"):
        parts.append("**潜在矛盾**：" + "；".join(analysis["contradictions"][:3]))
    if analysis.get("knowledge_gaps"):
        parts.append("**知识缺口**：" + "；".join(analysis["knowledge_gaps"][:3]))
    return "\n".join(parts) if parts else "（首次录入，暂无关联分析）"


# ── Public API ────────────────────────────────────────────────────────────────

def extract_insights(transcript: str, metadata: dict) -> str:
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n\n...[字幕已截断，仅处理前段内容]"

    from processors.purpose_manager import get_purpose_context
    purpose_context = get_purpose_context()
    existing_titles = _get_existing_titles()

    # Step 1: Analyze — extract entities, find cross-references, detect gaps
    analysis = _analyze_transcript(transcript, metadata, existing_titles, purpose_context)
    analysis_summary = _format_analysis_summary(analysis)

    # Step 2: Generate — write structured Wiki page with wikilinks
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": _WIKI_SYSTEM},
            {
                "role": "user",
                "content": _WIKI_PROMPT.format(
                    purpose_context=purpose_context,
                    title=metadata.get("title", "未知"),
                    channel=metadata.get("channel", "未知"),
                    url=metadata.get("url", ""),
                    analysis_summary=analysis_summary,
                    transcript=transcript,
                ),
            },
        ],
    )
    wiki_page = response.choices[0].message.content or ""

    # Append knowledge gaps section if analysis found gaps not already in the page
    gaps = analysis.get("knowledge_gaps", [])
    if gaps and "## 待研究缺口" not in wiki_page and "## 知识关联" not in wiki_page:
        gaps_text = "\n".join(f"- {g}" for g in gaps)
        wiki_page += f"\n\n## 待研究缺口\n{gaps_text}"

    return wiki_page


def parse_category(insights: str) -> str:
    match = re.search(r"##\s*分类\s*\n+([^\n#]+)", insights)
    if match:
        candidate = match.group(1).strip()
        for cat in CATEGORIES:
            if cat in candidate:
                return cat
    return "其他"
