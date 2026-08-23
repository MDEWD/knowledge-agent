import json

import pytest


@pytest.mark.asyncio
async def test_chat_tool_reads_imported_note_body(monkeypatch):
    import config

    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "test-key")
    import app
    from storage import notes_db

    monkeypatch.setattr(app, "get_video", lambda item_id: None)
    monkeypatch.setattr(
        notes_db,
        "get_note",
        lambda item_id: {
            "id": item_id,
            "title": "FedSPCA paper",
            "content": "The paper proposes a novel federated segmentation method.",
        },
    )

    result, suggestions, citations = await app._execute_tool(
        "get_knowledge_item",
        json.dumps({"item_id": "paper-1"}),
        None,
        None,
        "test-model",
    )

    assert "novel federated segmentation method" in result
    assert suggestions is None
    assert citations == [{
        "index": 1,
        "title": "FedSPCA paper",
        "url": "note://paper-1",
        "channel": "",
    }]
