from __future__ import annotations

import auth.context as auth_context
from auth.context import user_scope
from storage import bm25_store, notes_db, video_db


def test_video_and_note_files_are_isolated_by_user(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_context, "DATA_PATH", tmp_path)

    with user_scope("user-a"):
        video_db.add_video({"id": "a", "url": "https://a.example"})
        notes_db.add_note({"id": "a", "title": "A"})

    with user_scope("user-b"):
        assert video_db.list_videos() == []
        assert notes_db.list_notes() == []
        video_db.add_video({"id": "b", "url": "https://b.example"})

    with user_scope("user-a"):
        assert [item["id"] for item in video_db.list_videos()] == ["a"]
        assert [item["id"] for item in notes_db.list_notes()] == ["a"]


def test_bm25_index_is_isolated_by_user(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_context, "DATA_PATH", tmp_path)
    bm25_store._states.clear()

    with user_scope("user-a"):
        bm25_store.add_documents([
            {"id": "doc-a", "text": "半导体行业研究", "metadata": {"url": "https://a.example"}},
            {"id": "doc-b", "text": "黄金市场分析", "metadata": {"url": "https://b.example"}},
            {"id": "doc-c", "text": "人工智能应用", "metadata": {"url": "https://c.example"}},
        ])
        assert bm25_store.search("半导体")

    with user_scope("user-b"):
        assert bm25_store.search("半导体") == []
