import re
import httpx
from bilibili_api import video, sync

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
}


def _parse_subtitle_file(path: str) -> str:
    import os, re as _re
    with open(path, encoding="utf-8") as f:
        content = f.read()
    content = _re.sub(r"\d{2}:\d{2}:\d{2}[.,]\d{3} --> .*\n", "", content)
    content = _re.sub(r"<[^>]+>", "", content)
    content = _re.sub(r"^\d+$", "", content, flags=_re.MULTILINE)
    content = _re.sub(r"WEBVTT.*\n", "", content)
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    deduped, prev = [], None
    for line in lines:
        if line != prev:
            deduped.append(line)
        prev = line
    return " ".join(deduped)


def _extract_bvid(url: str) -> str:
    match = re.search(r"BV[a-zA-Z0-9]+", url)
    if match:
        return match.group()
    raise ValueError(f"无法从链接中提取 BV 号: {url}")


def _fetch_subtitle_json(sub_url: str) -> str:
    if sub_url.startswith("//"):
        sub_url = "https:" + sub_url
    resp = httpx.get(sub_url, headers=_HEADERS, verify=False, timeout=30)
    body = resp.json().get("body", [])
    return " ".join(item.get("content", "") for item in body)


def get_transcript(url: str) -> dict:
    bvid = _extract_bvid(url)
    v = video.Video(bvid=bvid)

    # 同步调用异步接口
    info = sync(v.get_info())
    metadata = {
        "title": info.get("title", "Unknown"),
        "channel": info.get("owner", {}).get("name", "Unknown"),
        "duration": info.get("duration", 0),
        "upload_date": str(info.get("pubdate", "")),
        "url": url,
        "platform": "bilibili",
    }

    # 优先：视频 info 里的字幕列表（已登录或 AI 字幕）
    sub_list = info.get("subtitle", {}).get("list", [])
    if sub_list:
        # 优先中文字幕
        sub = next(
            (s for s in sub_list if "zh" in s.get("lan", "").lower()),
            sub_list[0],
        )
        try:
            text = _fetch_subtitle_json(sub["subtitle_url"])
            if text.strip():
                return {"text": text, "metadata": metadata}
        except Exception:
            pass

    # 次选：通过 API 获取字幕（支持 AI 生成字幕）
    try:
        pages = info.get("pages", [{}])
        cid = pages[0].get("cid", 0)
        sub_info = sync(v.get_subtitle(cid=cid))
        subtitles = sub_info.get("subtitles", [])
        if subtitles:
            text = _fetch_subtitle_json(subtitles[0]["subtitle_url"])
            if text.strip():
                return {"text": text, "metadata": metadata}
    except Exception:
        pass

    # 兜底：Whisper 语音识别
    from extractors.whisper_fallback import transcribe
    text = transcribe(url)
    return {"text": text, "metadata": metadata}
