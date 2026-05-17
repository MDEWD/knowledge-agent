import re
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound


def _extract_video_id(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
    if match:
        return match.group(1)
    raise ValueError(f"Cannot parse YouTube video ID from: {url}")


_BASE_OPTS = {"quiet": True, "no_warnings": True, "nocheckcertificate": True}


def _get_metadata(url: str) -> dict:
    with yt_dlp.YoutubeDL(_BASE_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title", "Unknown"),
            "channel": info.get("uploader", "Unknown"),
            "duration": info.get("duration", 0),
            "upload_date": info.get("upload_date", ""),
            "url": url,
            "platform": "youtube",
        }


def get_transcript(url: str) -> dict:
    metadata = _get_metadata(url)
    video_id = _extract_video_id(url)

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        for lang in ["zh-Hans", "zh-CN", "zh", "en"]:
            try:
                t = transcript_list.find_transcript([lang])
                segments = t.fetch()
                text = " ".join(s["text"] for s in segments)
                return {"text": text, "metadata": metadata}
            except NoTranscriptFound:
                continue
        # Try any available
        t = transcript_list.find_generated_transcript(["zh-Hans", "zh", "en"])
        text = " ".join(s["text"] for s in t.fetch())
        return {"text": text, "metadata": metadata}
    except (TranscriptsDisabled, Exception):
        pass

    # Fallback: Whisper
    from extractors.whisper_fallback import transcribe
    text = transcribe(url)
    return {"text": text, "metadata": metadata}
