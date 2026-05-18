import json
import re
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from storage.video_db import list_videos
from extractors.youtube_search import search_youtube

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def generate_recommendations() -> list[dict]:
    videos = list_videos()
    if not videos:
        return []

    existing_urls = {v.get("url", "") for v in videos}
    summary_parts = [
        f"- 《{v['title']}》 分类:{v.get('category', '未知')} 标签:{','.join((v.get('tags') or [])[:5])}"
        for v in videos[:30]
    ]

    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        max_tokens=500,
        messages=[
            {"role": "system", "content": "你是学习规划专家，善于分析知识库并找出学习盲点。"},
            {"role": "user", "content": (
                f"以下是用户的视频知识库（{len(videos)}个视频）：\n\n"
                f"{chr(10).join(summary_parts)}\n\n"
                "请分析这个知识库，找出3个值得深入学习的相关主题（知识盲点或可以深化的方向）。"
                "每个主题给出：1) 适合搜索的关键词（中文，简短精准，5字以内）2) 推荐理由（1句话，20字以内）\n\n"
                '以JSON格式返回，不要有多余文字：{"topics": [{"topic": "...", "reason": "..."}]}'
            )},
        ],
    )

    content = resp.choices[0].message.content or ""
    try:
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group())
        topics = data.get("topics", [])[:3]
    except Exception:
        return []

    results = []
    for item in topics:
        topic = item.get("topic", "").strip()
        reason = item.get("reason", "").strip()
        if not topic:
            continue
        found = search_youtube(topic, limit=4)
        filtered = [v for v in found if v.get("url") not in existing_urls][:3]
        results.append({"topic": topic, "reason": reason, "videos": filtered})

    return results
