import re
from datetime import datetime
from pathlib import Path
from config import OBSIDIAN_VAULT_PATH
from processors.insights import parse_category


def save_to_obsidian(insights: str, metadata: dict, transcript: str = "", original_transcript: str = "") -> Path:
    category = parse_category(insights)
    category_dir = OBSIDIAN_VAULT_PATH / category
    category_dir.mkdir(parents=True, exist_ok=True)

    title = metadata.get("title", "untitled")
    safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", title)[:80].strip()
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str} {safe_title}.md"
    filepath = category_dir / filename

    filepath.write_text(_build_content(title, transcript, insights, date_str, metadata, category, original_transcript), encoding="utf-8")
    return filepath


def update_obsidian_note(obsidian_path: str, title: str, transcript: str, new_insights: str) -> None:
    path = Path(obsidian_path)
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    insights_body = re.sub(r"##\s*分类\s*\n+[^\n#]+\n*", "", new_insights).strip()

    sep = "\n\n---\n\n"
    if sep in content:
        # Replace everything after the last --- separator (end of transcript section)
        pre = content[:content.rfind(sep) + len(sep)]
        path.write_text(pre + insights_body, encoding="utf-8")
    else:
        # No transcript section — replace everything after # title heading
        title_marker = f"# {title}\n\n"
        idx = content.find(title_marker)
        if idx != -1:
            path.write_text(content[:idx + len(title_marker)] + insights_body, encoding="utf-8")


def _build_content(title: str, transcript: str, insights: str, date_str: str, metadata: dict, category: str, original_transcript: str = "") -> str:
    frontmatter = (
        f"---\n"
        f"title: \"{title.replace(chr(34), chr(39))}\"\n"
        f"source: \"{metadata.get('url', '')}\"\n"
        f"channel: \"{metadata.get('channel', '')}\"\n"
        f"platform: \"{metadata.get('platform', '')}\"\n"
        f"category: \"{category}\"\n"
        f"date: {date_str}\n"
        f"type: video-note\n"
        f"---\n\n"
    )

    transcript_section = ""
    if original_transcript.strip():
        transcript_section = (
            f"## 原始文案（英文）\n\n{original_transcript.strip()}\n\n"
            f"## 中文翻译\n\n{transcript.strip()}\n\n---\n\n"
        )
    elif transcript.strip():
        transcript_section = f"## 原始文案\n\n{transcript.strip()}\n\n---\n\n"

    insights_body = re.sub(r"##\s*分类\s*\n+[^\n#]+\n*", "", insights).strip()
    return frontmatter + f"# {title}\n\n" + transcript_section + insights_body

