from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, MAX_TRANSCRIPT_CHARS

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

CATEGORIES = [
    "财经理财", "AI与科技", "心理学", "商业创业", "健康生活",
    "教育学习", "历史文化", "娱乐综艺", "科学探索", "其他",
]

_SYSTEM = "你是一个知识提炼专家。给定视频字幕，提炼出结构化的知识笔记，用中文输出，Markdown 格式。"

_PROMPT = """\
请对以下视频字幕进行知识提炼：

**视频标题**：{title}
**频道**：{channel}
**链接**：{url}

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
（列出重要术语/概念，格式：`概念名` - 简短解释）

## 行动启示
（可以立即应用的建议或思维方式）

## 标签
（5-8个相关标签，格式：#标签1 #标签2 ...）
"""

_TRANSLATE_CHUNK = 3000


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
                    "content": "你是专业翻译。将以下内容翻译成中文，保持原意和段落结构，只输出译文，不要任何解释。",
                },
                {"role": "user", "content": chunk},
            ],
        )
        parts.append(resp.choices[0].message.content or chunk)
    return "\n\n".join(parts)


def extract_insights(transcript: str, metadata: dict) -> str:
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n\n...[字幕已截断，仅处理前段内容]"

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": _PROMPT.format(
                    title=metadata.get("title", "未知"),
                    channel=metadata.get("channel", "未知"),
                    url=metadata.get("url", ""),
                    transcript=transcript,
                ),
            },
        ],
    )
    return response.choices[0].message.content or ""


def parse_category(insights: str) -> str:
    import re
    match = re.search(r"##\s*分类\s*\n+([^\n#]+)", insights)
    if match:
        candidate = match.group(1).strip()
        for cat in CATEGORIES:
            if cat in candidate:
                return cat
    return "其他"


client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

CATEGORIES = [
    "财经理财",
    "AI与科技",
    "心理学",
    "商业创业",
    "健康生活",
    "教育学习",
    "历史文化",
    "娱乐综艺",
    "科学探索",
    "其他",
]

_SYSTEM = "你是一个知识提炼专家。给定视频字幕，提炼出结构化的知识笔记，用中文输出，Markdown 格式。"

_PROMPT = """\
请对以下视频字幕进行知识提炼：

**视频标题**：{title}
**频道**：{channel}
**链接**：{url}

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
（列出重要术语/概念，格式：`概念名` - 简短解释）

## 行动启示
（可以立即应用的建议或思维方式）

## 标签
（5-8个相关标签，格式：#标签1 #标签2 ...）
"""


def extract_insights(transcript: str, metadata: dict) -> str:
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n\n...[字幕已截断，仅处理前段内容]"

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": _PROMPT.format(
                    title=metadata.get("title", "未知"),
                    channel=metadata.get("channel", "未知"),
                    url=metadata.get("url", ""),
                    transcript=transcript,
                ),
            },
        ],
    )
    return response.choices[0].message.content or ""


def parse_category(insights: str) -> str:
    """Extract the category from the ## 分类 section of insights."""
    import re
    match = re.search(r"##\s*分类\s*\n+([^\n#]+)", insights)
    if match:
        candidate = match.group(1).strip()
        for cat in CATEGORIES:
            if cat in candidate:
                return cat
    return "其他"
