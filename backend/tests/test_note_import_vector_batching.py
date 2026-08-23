def test_note_import_upserts_vector_chunks_in_bounded_batches(monkeypatch):
    from storage import vector_store

    calls = []

    class FakeCollection:
        def upsert(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(vector_store, "_get_collection", lambda: FakeCollection())
    monkeypatch.setattr(vector_store, "_UPSERT_BATCH_SIZE", 2)
    monkeypatch.setattr(vector_store.bm25_store, "add_documents", lambda items: None)
    monkeypatch.setattr(vector_store, "get_current_user_id", lambda: "test-user")

    vector_store.add_note_document(
        ". ".join(f"Sentence {i}, this is sufficiently long test content with more words to force chunking" for i in range(15)),
        {"id": "n1", "title": "测试", "url": "note://n1"},
    )

    assert len(calls) >= 2
    assert all(len(call["ids"]) <= 2 for call in calls)
    assert sum(len(call["ids"]) for call in calls) == sum(
        len(call["documents"]) for call in calls
    )
