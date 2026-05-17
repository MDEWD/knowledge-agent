import re
from datetime import datetime
from pathlib import Path
from config import OBSIDIAN_VAULT_PATH
from processors.insights import parse_category


def save_to_obsidian(insights: str, metadata: dict, transcript: str = "") -> Path:
    category = parse_category(insights)
    category_dir = OBSIDIAN_VAULT_PATH / category
    category_dir.mkdir(parents=True, exist_ok=True)

    title = metadata.get("title", "untitled")
    safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", title)[:80].strip()
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str} {safe_title}.md"
    filepath = category_dir / filename

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
    if transcript.strip():
        transcript_section = f"## 原始文案\n\n{transcript.strip()}\n\n---\n\n"

    # Remove the ## 分类 section from insights before writing (it's already in frontmatter)
    insights_body = re.sub(r"##\s*分类\s*\n+[^\n#]+\n*", "", insights).strip()

    content = frontmatter + f"# {title}\n\n" + transcript_section + insights_body
    filepath.write_text(content, encoding="utf-8")
    return filepath
