def test_doc_extension_uses_legacy_word_extractor(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "test-key")
    from processors import note_importer

    source = tmp_path / "legacy.doc"
    source.write_bytes(bytes.fromhex("D0 CF 11 E0 A1 B1 1A E1"))
    monkeypatch.setattr(note_importer, "_extract_legacy_doc", lambda path: "legacy body")

    assert note_importer.extract_text(source, "doc") == "legacy body"
