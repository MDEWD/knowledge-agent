import re
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

_CHUNK_SIZE = 2500   # chars per LLM chunk
_MAX_CHUNKS = 6      # max chunks to process (covers ~15000 chars / ~10 min video)


def _is_conversation(sample: str) -> bool:
    """Quick LLM check: is this transcript a multi-speaker conversation?"""
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        max_tokens=5,
        messages=[
            {"role": "system", "content": "只回答「是」或「否」，不要其他内容。"},
            {"role": "user", "content": (
                "以下字幕是否为多人对话（访谈、对谈、辩论、问答）？"
                "如果是一个人在讲述/演讲/教程回答「否」。\n\n"
                f"{sample[:1200]}"
            )},
        ],
    )
    answer = resp.choices[0].message.content or ""
    return "是" in answer


def _diarize_chunk(chunk: str, known_speakers: str) -> str:
    """
    Label speaker turns in one chunk.
    known_speakers: comma-separated list of speaker labels already identified
                    (passed across chunks for consistency).
    """
    context = f"本视频已出现的说话人：{known_speakers}。请保持标签一致。\n\n" if known_speakers else ""
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        max_tokens=2000,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是专业字幕编辑。规则：\n"
                    "1. 在每次说话人切换时另起一行，并在行首加【说话人标签】\n"
                    "2. 能识别出姓名/职称就用真实名字，否则用「A」「B」等字母\n"
                    "3. 不得删减、改写任何内容，只添加标签和换行\n"
                    "4. 保留原文所有标点和词语"
                ),
            },
            {
                "role": "user",
                "content": f"{context}请标注以下片段的说话人：\n\n{chunk}",
            },
        ],
    )
    return resp.choices[0].message.content or chunk


def _extract_speakers(text: str) -> str:
    """Pull out all 【xxx】 labels found in diarized text."""
    found = re.findall(r'【([^】]+)】', text)
    seen: list[str] = []
    for s in found:
        if s not in seen:
            seen.append(s)
    return "、".join(seen)


def detect_and_diarize(text: str) -> str:
    """
    Main entry point.
    - Detects whether transcript is a multi-speaker conversation.
    - If yes, processes in chunks and returns speaker-labelled transcript.
    - If no (single speaker), returns the original text unchanged.
    """
    if len(text.strip()) < 300:
        return text

    if not _is_conversation(text):
        return text

    # Split into chunks, preserving word boundaries
    chunks: list[str] = []
    start = 0
    while start < len(text) and len(chunks) < _MAX_CHUNKS:
        end = start + _CHUNK_SIZE
        if end < len(text):
            # Try to break at a sentence boundary
            boundary = max(
                text.rfind("。", start, end),
                text.rfind(".", start, end),
                text.rfind(" ", start, end),
            )
            if boundary > start:
                end = boundary + 1
        chunks.append(text[start:end])
        start = end

    diarized_parts: list[str] = []
    known_speakers = ""
    for chunk in chunks:
        result = _diarize_chunk(chunk, known_speakers)
        diarized_parts.append(result)
        known_speakers = _extract_speakers("\n".join(diarized_parts))

    diarized = "\n\n".join(diarized_parts)

    # Sanity check: if LLM returned much less content than input, fall back
    if len(diarized) < len(text) * 0.6:
        return text

    # Append a note if transcript was truncated (very long video)
    if len(text) > _CHUNK_SIZE * _MAX_CHUNKS:
        diarized += "\n\n*（文案较长，以上为前半段说话人标注，后续内容已省略标注）*"

    return diarized
