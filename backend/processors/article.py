import re
from datetime import datetime
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, OBSIDIAN_VAULT_PATH
from storage.vector_store import search, find_related, is_topic_covered
from storage.video_db import list_videos, get_video

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def generate_article(topic: str) -> dict:
    # Gate: reject before calling LLM if KB has no relevant content
    if not is_topic_covered(topic, min_chunks=2, max_distance=1.0):
        return {
            "article": "", "path": "",
            "error": f"知识库中暂无「{topic}」的相关内容，建议先添加相关视频再生成文章",
        }

    results = search(topic, n_results=20)
    if not results:
        return {"article": "", "path": "", "error": "知识库中没有相关内容"}

    seen: dict[str, dict] = {}
    chunks = []
    for r in results:
        meta = r["metadata"]
        key = meta.get("video_id") or meta.get("title", "")
        if key not in seen:
            seen[key] = {"title": meta.get("title", ""), "url": meta.get("url", "")}
        chunks.append(f"【{meta.get('title', '')}】{r['content']}")

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": "你是知识整合专家，善于从多个来源提炼系统性文章。"},
            {"role": "user", "content": (
                f"基于以下知识库内容，撰写一篇关于「{topic}」的系统性综合文章。\n"
                "要求：逻辑清晰，有引言/主体/结论；综合多视频观点，找出共识和分歧；"
                "引用某视频观点时用「（来自：视频标题）」标注；"
                "结尾加「## 参考来源」章节列出所有引用的视频及链接。\n\n"
                f"知识库内容：\n\n{chr(10).join(chunks[:15])}"
            )},
        ],
    )

    article = response.choices[0].message.content or ""
    date_str = datetime.now().strftime("%Y-%m-%d")
    article_dir = OBSIDIAN_VAULT_PATH / "综合文章"
    article_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[<>:"/\\|?*]', '-', topic)[:50]
    filepath = article_dir / f"{date_str} {safe}.md"
    filepath.write_text(
        f"---\ntype: synthesis\ntopic: \"{topic}\"\ndate: {date_str}\n---\n\n{article}",
        encoding="utf-8",
    )

    return {"article": article, "path": str(filepath), "source_count": len(seen)}


def list_articles() -> list[dict]:
    article_dir = OBSIDIAN_VAULT_PATH / "综合文章"
    if not article_dir.exists():
        return []
    articles = []
    for f in sorted(article_dir.glob("*.md"), reverse=True):
        try:
            content = f.read_text(encoding="utf-8")
            topic_match = re.search(r'topic: "([^"]+)"', content)
            date_match = re.search(r'date: (\S+)', content)
            topic = topic_match.group(1) if topic_match else f.stem
            date = date_match.group(1) if date_match else f.stem[:10]
            body = re.sub(r'---.*?---\n\n', '', content, flags=re.DOTALL).strip()
            articles.append({
                "filename": f.name,
                "topic": topic,
                "date": date,
                "preview": body[:200],
                "content": body,
            })
        except Exception:
            pass
    return articles


def summarize_category_impl(category: str) -> str:
    videos = [v for v in list_videos() if v.get("category") == category]
    if not videos:
        return f"分类「{category}」下没有视频。"

    summaries = "\n\n".join([
        f"**{v['title']}**: {v.get('summary', '无摘要')}"
        for v in videos
    ])

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": "你是知识总结专家。"},
            {"role": "user", "content": (
                f"请对「{category}」分类下的 {len(videos)} 个视频进行综合总结，"
                f"找出共同主题和核心观点：\n\n{summaries}"
            )},
        ],
    )
    return response.choices[0].message.content or ""


def compare_videos_impl(video_ids: list, topic: str = "") -> str:
    parts = []
    for vid_id in video_ids:
        v = get_video(vid_id)
        if v:
            parts.append(f"**{v['title']}**\n{(v.get('insights') or v.get('summary', ''))[:800]}")

    if not parts:
        return "未找到指定的视频。"

    topic_hint = f"，重点对比「{topic}」这个角度" if topic else ""
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": "你是知识分析专家。"},
            {"role": "user", "content": (
                f"请对比以下 {len(parts)} 个视频的核心观点{topic_hint}，"
                f"找出共识、分歧和互补之处：\n\n{'---'.join(parts)}"
            )},
        ],
    )
    return response.choices[0].message.content or ""
