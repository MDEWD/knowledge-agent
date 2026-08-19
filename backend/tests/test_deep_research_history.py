from storage import deep_research_history as history


def test_follow_up_turn_is_appended_and_completed_without_overwriting_previous():
    turns = [{"question": "第一轮问题", "answer": "第一轮报告"}]

    pending, turn_index = history.append_pending_turn(turns, "第二轮追问")
    completed = history.complete_turn(
        pending,
        turn_index,
        question="第二轮追问",
        answer="第二轮报告",
    )

    assert turn_index == 1
    assert completed == [
        {"question": "第一轮问题", "answer": "第一轮报告"},
        {"question": "第二轮追问", "answer": "第二轮报告"},
    ]


def test_identical_follow_up_question_still_creates_a_new_turn():
    turns = [{"question": "继续分析风险", "answer": "第一份报告"}]

    pending, turn_index = history.append_pending_turn(turns, "继续分析风险")

    assert turn_index == 1
    assert len(pending) == 2
    assert pending[0]["answer"] == "第一份报告"


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
