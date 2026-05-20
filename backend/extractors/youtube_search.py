import yt_dlp


def search_youtube(query: str, limit: int = 5) -> list[dict]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "nocheckcertificate": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            videos = []
            for entry in info.get("entries") or []:
                if not entry:
                    continue
                vid_id = entry.get("id", "")
                if not vid_id:
                    continue
                videos.append({
                    "title": entry.get("title", ""),
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                    "channel": entry.get("uploader") or entry.get("channel", ""),
                    "duration": entry.get("duration"),
                })
            return videos
    except Exception:
        return []
