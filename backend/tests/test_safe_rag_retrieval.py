def test_bm25_search_does_not_initialize_native_models_when_disabled(monkeypatch):
    from storage import vector_store

    monkeypatch.setattr(vector_store, "LOCAL_RAG_MODELS_ENABLED", False)
    monkeypatch.setattr(
        vector_store, "_get_collection", lambda: (_ for _ in ()).throw(
            AssertionError("native embedding model must not be initialized")
        )
    )
    monkeypatch.setattr(vector_store.bm25_store, "search", lambda query, n: [("note-1", 1.0)])
    monkeypatch.setattr(
        vector_store.bm25_store,
        "get_doc_by_id",
        lambda doc_id: {
            "text": "Imported note content",
            "metadata": {"title": "Imported note", "url": "note://1", "chunk_index": 0},
        },
    )

    assert vector_store.search("note", n_results=3)[0]["content"] == "Imported note content"
