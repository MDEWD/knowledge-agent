def test_local_backend_env_overrides_inherited_docker_settings(monkeypatch, tmp_path):
    from env_loader import load_runtime_environment

    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / ".env").write_text(
        "MYSQL_USER=root\nMYSQL_PASSWORD=local-secret\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "MYSQL_USER=zhiyan\nAUTH_COOKIE_SECURE=true\n"
        "CORS_ORIGINS=https://zhiresearch.com\n"
        "AUTH_ADMIN_EMAILS=1539570130@qq.com\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MYSQL_USER", "zhiyan")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("CORS_ORIGINS", "https://zhiresearch.com")

    load_runtime_environment(backend_dir, tmp_path)

    import os
    assert os.environ["MYSQL_USER"] == "root"
    assert os.environ["AUTH_COOKIE_SECURE"] == "false"
    assert os.environ["CORS_ORIGINS"] == "http://localhost:5173,http://localhost:3000"
    assert os.environ["AUTH_ADMIN_EMAILS"] == "1539570130@qq.com"


def test_container_environment_is_untouched_without_backend_env(monkeypatch, tmp_path):
    from env_loader import load_runtime_environment

    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    monkeypatch.setenv("MYSQL_USER", "zhiyan")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")

    load_runtime_environment(backend_dir, tmp_path)

    import os
    assert os.environ["MYSQL_USER"] == "zhiyan"
    assert os.environ["AUTH_COOKIE_SECURE"] == "true"
