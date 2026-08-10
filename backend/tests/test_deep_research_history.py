from storage import deep_research_history as history


def test_deep_research_history_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_STORAGE_BACKEND", "json")
    history_file = tmp_path / "deep_research_history.json"
    monkeypatch.setattr(history, "_HISTORY_FILE", history_file)

    assert history.list_sessions() == []

    created = history.upsert_session({
        "id": "session-1",
        "title": "半导体趋势",
        "run_id": "run-1",
        "evidence": [{
            "source_id": "src-1",
            "query": "policy source",
            "title": "Policy document",
            "url": "https://example.com/policy",
            "snippet": "Policy summary",
            "status": "summarized",
        }],
        "turns": [{"question": "趋势如何？", "answer": "报告正文"}],
    })

    assert created["created_at"]
    assert history.get_session("session-1")["evidence"][0]["url"] == "https://example.com/policy"
    assert history.get_session("session-1")["turns"][0]["answer"] == "报告正文"
    assert history.list_sessions() == [{
        "id": "session-1",
        "title": "半导体趋势",
        "run_id": "run-1",
        "created_at": created["created_at"],
        "updated_at": created["updated_at"],
        "turn_count": 1,
    }]

    updated = history.upsert_session({
        "id": "session-1",
        "title": "半导体趋势（更新）",
        "run_id": "run-2",
        "turns": [
            {"question": "趋势如何？", "answer": "报告正文"},
            {"question": "主要风险？", "answer": "风险正文"},
        ],
    })
    assert updated["created_at"] == created["created_at"]
    assert history.list_sessions()[0]["turn_count"] == 2

    assert history.delete_session("session-1") is True
    assert history.delete_session("session-1") is False
    assert history.get_session("session-1") is None
