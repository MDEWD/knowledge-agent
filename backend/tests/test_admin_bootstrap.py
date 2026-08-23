def test_configured_existing_admin_is_promoted_without_password_change(monkeypatch):
    from auth import service

    executed = {}

    class Cursor:
        rowcount = 1

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params):
            executed["sql"] = sql
            executed["params"] = params

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return Cursor()

    class Pool:
        def connection(self):
            return Connection()

    monkeypatch.setattr(service, "AUTH_ADMIN_EMAILS", {"1539570130@qq.com"})
    monkeypatch.setattr(service, "get_pool", lambda: Pool())

    assert service.ensure_configured_admins() == 1
    assert executed["params"] == ("1539570130@qq.com",)
    assert "password" not in executed["sql"].lower()


def test_no_configured_admins_does_not_connect_to_database(monkeypatch):
    from auth import service

    monkeypatch.setattr(service, "AUTH_ADMIN_EMAILS", set())
    monkeypatch.setattr(
        service,
        "get_pool",
        lambda: (_ for _ in ()).throw(AssertionError("database should not be accessed")),
    )

    assert service.ensure_configured_admins() == 0
