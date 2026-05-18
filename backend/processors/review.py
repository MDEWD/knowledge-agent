import re
from datetime import datetime, timedelta
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, OBSIDIAN_VAULT_PATH
from storage.video_db import list_videos

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

_PROMPT = """\
本期复盘周期：过去 {days} 天
新增视频数量：{count} 个

以下是本期新增的视频笔记摘要：
{context}

---
请生成一份知识复盘报告，包含以下结构：

## 本期学习总结
（2-3句话，概括本期学习的整体方向和收获）

## 重要新知识点
（列出最值得记住的 5-8 个知识点，每个加一句说明）

## 知识连接与洞见
（找出本期内容之间的关联，或与已有知识的连接，这是最有价值的部分）

## 值得深入的方向
（基于本期内容，推荐 2-3 个下一步可以深入探索的方向，并说明理由）

## 行动清单
（列出 3-5 件可以马上去做的事情）
"""


def _parse_dt(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.min


def generate_weekly_review(days: int = 7) -> dict:
    cutoff = datetime.now() - timedelta(days=days)
    recent = [v for v in list_videos() if _parse_dt(v.get("created_at", "")) >= cutoff]

    date_str = datetime.now().strftime("%Y-%m-%d")

    if not recent:
        return {"report": "", "video_count": 0, "saved_path": "", "date": date_str, "video_titles": []}

    summaries = []
    for v in recent:
        summaries.append(
            f"**{v['title']}** (分类: {v.get('category', '其他')})\n"
            f"摘要: {v.get('summary', '无摘要')}\n"
            f"标签: {', '.join(v.get('tags', []))}"
        )

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": "你是个人知识管理助手，帮用户做深度学习复盘。"},
            {"role": "user", "content": _PROMPT.format(
                days=days, count=len(recent),
                context="\n\n---\n\n".join(summaries),
            )},
        ],
    )

    report = response.choices[0].message.content or ""
    review_dir = OBSIDIAN_VAULT_PATH / "复盘报告"
    review_dir.mkdir(parents=True, exist_ok=True)
    filepath = review_dir / f"{date_str} 周复盘（{len(recent)}个视频）.md"
    filepath.write_text(
        f"---\ntype: weekly-review\ndate: {date_str}\nvideos: {len(recent)}\n---\n\n{report}",
        encoding="utf-8",
    )

    return {
        "report": report,
        "video_count": len(recent),
        "saved_path": str(filepath),
        "date": date_str,
        "video_titles": [v["title"] for v in recent],
    }


def list_reviews() -> list[dict]:
    review_dir = OBSIDIAN_VAULT_PATH / "复盘报告"
    if not review_dir.exists():
        return []
    reviews = []
    for f in sorted(review_dir.glob("*.md"), reverse=True):
        try:
            content = f.read_text(encoding="utf-8")
            date_match = re.search(r"date: (\S+)", content)
            videos_match = re.search(r"videos: (\d+)", content)
            date = date_match.group(1) if date_match else f.stem[:10]
            video_count = int(videos_match.group(1)) if videos_match else 0
            body = re.sub(r"---.*?---\n\n", "", content, flags=re.DOTALL).strip()
            reviews.append({
                "filename": f.name,
                "date": date,
                "video_count": video_count,
                "preview": body[:200],
                "content": body,
            })
        except Exception:
            pass
    return reviews
