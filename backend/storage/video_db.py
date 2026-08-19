import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional
from auth.context import user_data_path

_LOCK = threading.RLock()


def _db_file() -> Path:
    return user_data_path("videos.json")


def _load() -> list[dict]:
    db_file = _db_file()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    if not db_file.exists():
        return []
    return json.loads(db_file.read_text(encoding="utf-8"))


def _save(videos: list[dict]) -> None:
    db_file = _db_file()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    temp = db_file.with_suffix(".tmp")
    temp.write_text(json.dumps(videos, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(db_file)


def add_video(video: dict) -> None:
    with _LOCK:
        videos = _load()
        videos = [v for v in videos if v.get("url") != video.get("url")]
        videos.insert(0, video)
        _save(videos)


def list_videos() -> list[dict]:
    with _LOCK:
        return _load()


def get_video(video_id: str) -> Optional[dict]:
    return next((v for v in _load() if v.get("id") == video_id), None)


def update_video_note(video_id: str, new_insights: str) -> bool:
    with _LOCK:
        videos = _load()
        for v in videos:
            if v.get("id") == video_id:
                v["insights"] = new_insights
                _save(videos)
                return True
    return False


def delete_video(video_id: str) -> bool:
    with _LOCK:
        videos = _load()
        new_videos = [v for v in videos if v.get("id") != video_id]
        if len(new_videos) == len(videos):
            return False
        _save(new_videos)
        return True


def batch_update_significance(scores: dict[str, float]) -> None:
    """Bulk-update significance_score field for all videos in the scores dict."""
    with _LOCK:
        videos = _load()
        for v in videos:
            vid_id = v.get("id", "")
            if vid_id in scores:
                v["significance_score"] = scores[vid_id]
        _save(videos)
