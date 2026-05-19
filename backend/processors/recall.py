import json
import re
import uuid
from datetime import date, timedelta

from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from storage.recall_db import add_cards, list_cards, update_card
from storage.video_db import get_video

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def generate_cards_for_video(video_id: str, count: int = 5) -> list[dict]:
    video = get_video(video_id)
    if not video:
        return []
    insights = video.get("insights", "") or video.get("summary", "")
    if not insights:
        return []

    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        max_tokens=2000,
        messages=[
            {
                "role": "system",
                "content": "你是知识提炼专家，专门从学习材料中提取核心知识点，只输出JSON，不要任何解释。",
            },
            {
                "role": "user",
                "content": (
                    f"基于以下学习笔记，生成 {count} 道主动回忆卡片（问答形式）。\n"
                    "要求：\n"
                    "1. 每道题测试一个具体知识点，不要笼统提问\n"
                    "2. 答案简洁有力（1-3句话）\n"
                    '3. 格式：JSON数组 [{"question": "...", "answer": "..."}]\n\n'
                    f"学习笔记：\n{insights[:3000]}"
                ),
            },
        ],
    )

    raw = resp.choices[0].message.content or "[]"
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        qa_list = json.loads(match.group())
    except Exception:
        return []

    today = date.today().isoformat()
    cards = []
    for qa in qa_list[:count]:
        if not qa.get("question") or not qa.get("answer"):
            continue
        cards.append(
            {
                "id": str(uuid.uuid4())[:8],
                "video_id": video_id,
                "video_title": video.get("title", ""),
                "question": qa["question"],
                "answer": qa["answer"],
                "created_at": today,
                "next_review": today,
                "interval": 1,
                "ease_factor": 2.5,
                "repetitions": 0,
            }
        )

    add_cards(cards)
    return cards


def sm2_update(card: dict, quality: int) -> dict:
    """SM-2 algorithm. quality: 1-5 (1=blackout, 5=perfect recall)."""
    ef = float(card.get("ease_factor", 2.5))
    reps = int(card.get("repetitions", 0))
    interval = int(card.get("interval", 1))

    if quality < 3:
        reps = 0
        interval = 1
    else:
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = max(1, round(interval * ef))
        reps += 1

    ef = max(1.3, ef + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    next_review = (date.today() + timedelta(days=interval)).isoformat()
    return {
        "interval": interval,
        "ease_factor": round(ef, 2),
        "repetitions": reps,
        "next_review": next_review,
        "last_quality": quality,
        "last_reviewed": date.today().isoformat(),
    }


def review_card(card_id: str, quality: int) -> dict | None:
    all_cards = list_cards()
    card = next((c for c in all_cards if c["id"] == card_id), None)
    if not card:
        return None
    updates = sm2_update(card, quality)
    update_card(card_id, updates)
    return {**card, **updates}
