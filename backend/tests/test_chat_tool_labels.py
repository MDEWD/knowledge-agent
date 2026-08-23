def test_combined_knowledge_base_listing_is_not_labeled_as_video_only(monkeypatch):
    import config

    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "test-key")
    import app

    assert app._TOOL_LABELS["list_videos_in_kb"] == "列出知识库内容"
