import re
import yt_dlp
from urllib.parse import urlparse


def detect_platform(url: str) -> str:
    host = urlparse(url).hostname or ""
    if "youtube" in host or "youtu.be" in host:
        return "youtube"
    if "bilibili" in host or "b23.tv" in host:
        return "bilibili"
    return "generic"


def get_transcript(url: str) -> dict:
    """Generic extractor using yt-dlp + Whisper fallback for any platform."""
    import tempfile, os

    _BASE = {"quiet": True, "no_warnings": True, "nocheckcertificate": True, "legacy_server_connect": True}

    with yt_dlp.YoutubeDL(_BASE) as ydl:
        info = ydl.extract_info(url, download=False)
        metadata = {
            "title": info.get("title", "Unknown"),
            "channel": info.get("uploader", "Unknown"),
            "duration": info.get("duration", 0),
            "upload_date": info.get("upload_date", ""),
            "url": url,
            "platform": urlparse(url).hostname or "unknown",
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        opts = {
            **_BASE,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["zh-Hans", "zh", "en"],
            "skip_download": True,
            "outtmpl": f"{tmpdir}/sub",
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        for fname in os.listdir(tmpdir):
            if fname.endswith((".vtt", ".srt")):
                from extractors.bilibili import _parse_subtitle_file
                text = _parse_subtitle_file(os.path.join(tmpdir, fname))
                if text.strip():
                    return {"text": text, "metadata": metadata}

    from extractors.whisper_fallback import transcribe
    text = transcribe(url)
    return {"text": text, "metadata": metadata}
