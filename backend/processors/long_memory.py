import json
import re
from datetime import datetime

from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from storage.memory_store import load as load_memory, save as save_memory

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def get_memory_context() -> str:
    """Format current memory as a system prompt injection. Fast (file read only)."""
    mem = load_memory()
    if not any([mem.get("summary"), mem.get("interests"), mem.get("learning_goals")]):
        return ""
    parts = ["【用户记忆】"]
    if mem.get("summary"):
        parts.append(f"用户画像：{mem['summary']}")
    if mem.get("interests"):
        parts.append(f"学习兴趣：{', '.join(mem['interests'][:8])}")
    if mem.get("learning_goals"):
        parts.append(f"学习目标：{', '.join(mem['learning_goals'][:5])}")
    if mem.get("gaps"):
        parts.append(f"知识盲点：{', '.join(mem['gaps'][:5])}")
    if mem.get("key_insights"):
        parts.append("近期洞察：" + "；".join(mem["key_insights"][-3:]))
    return "\n".join(parts)


def update_memory_from_conversation(conversation: list[dict]) -> dict:
    """Extract memory-worthy info from conversation and merge into store (background)."""
    current = load_memory()
    text = "\n".join(
        f"[{m['role']}]: {m.get('content') or ''}"
        for m in conversation[-12:]
        if isinstance(m.get("content"), str) and m.get("content", "").strip()
    )
    if not text.strip():
        return current

    try:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            max_tokens=500,
            messages=[
                {
                    "role": "system",
                    "content": "你是记忆整理专家，从对话中提取用户信息。只输出JSON，不要解释。",
                },
                {
                    "role": "user",
                    "content": (
                        f"现有用户画像：{current.get('summary', '（暂无）')}\n\n"
                        f"对话内容：\n{text}\n\n"
                        "从对话提取新信息（没有新信息则对应字段返回空数组/空字符串）：\n"
                        "- interests: 兴趣话题\n"
                        "- learning_goals: 学习目标\n"
                        "- gaps: 知识盲点或困惑\n"
                        "- key_insights: 值得记住的洞察\n"
                        "- summary: 更新后的用户一句话画像（无变化则返回空字符串）\n"
                        '{"interests":[],"learning_goals":[],"gaps":[],"key_insights":[],"summary":""}'
                    ),
                },
            ],
        )
    except Exception:
        return current

    raw = resp.choices[0].message.content or "{}"
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return current
    try:
        extracted = json.loads(match.group())
    except Exception:
        return current

    def merge_list(old: list, new: list, max_n: int = 20) -> list:
        seen = set(old)
        combined = list(old)
        for item in new:
            if item and item not in seen:
                seen.add(item)
                combined.append(item)
        return combined[-max_n:]

    updated = {
        **current,
        "interests": merge_list(current.get("interests", []), extracted.get("interests", [])),
        "learning_goals": merge_list(current.get("learning_goals", []), extracted.get("learning_goals", [])),
        "gaps": merge_list(current.get("gaps", []), extracted.get("gaps", [])),
        "key_insights": merge_list(current.get("key_insights", []), extracted.get("key_insights", []), max_n=30),
        "updated_at": datetime.now().isoformat(),
    }
    if extracted.get("summary"):
        updated["summary"] = extracted["summary"]
    save_memory(updated)
    return updated
