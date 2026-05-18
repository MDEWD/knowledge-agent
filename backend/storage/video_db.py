import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from config import DATA_PATH

_DB_FILE = DATA_PATH / "videos.json"


def _load() -> list[dict]:
    _DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _DB_FILE.exists():
        return []
    return json.loads(_DB_FILE.read_text(encoding="utf-8"))


def _save(videos: list[dict]) -> None:
    _DB_FILE.write_text(json.dumps(videos, ensure_ascii=False, indent=2), encoding="utf-8")


def add_video(video: dict) -> None:
    videos = _load()
    videos = [v for v in videos if v.get("url") != video.get("url")]
    videos.insert(0, video)
    _save(videos)


def list_videos() -> list[dict]:
    return _load()


def get_video(video_id: str) -> Optional[dict]:
    return next((v for v in _load() if v.get("id") == video_id), None)


def update_video_note(video_id: str, new_insights: str) -> bool:
    videos = _load()
    for v in videos:
        if v.get("id") == video_id:
            v["insights"] = new_insights
            _save(videos)
            return True
    return False


def delete_video(video_id: str) -> bool:
    videos = _load()
    new_videos = [v for v in videos if v.get("id") != video_id]
    if len(new_videos) == len(videos):
        return False
    _save(new_videos)
    return True
