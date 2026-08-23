"""Deterministic local-vs-container environment loading."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


_LOCAL_DEFAULTS = {
    "AUTH_COOKIE_SECURE": "false",
    "CORS_ORIGINS": "http://localhost:5173,http://localhost:3000",
}
_SHARED_ADMIN_KEYS = (
    "AUTH_ADMIN_EMAILS",
    "DEFAULT_ADMIN_EMAIL",
    "DEFAULT_ADMIN_PASSWORD",
)


def load_runtime_environment(backend_dir: Path, project_root: Path) -> bool:
    """Load local settings when backend/.env exists; preserve container env otherwise."""
    local_path = backend_dir / ".env"
    if not local_path.exists():
        return False

    local_values = dotenv_values(local_path)
    # Local settings intentionally override variables inherited from a shell
    # previously used for Docker deployment.
    load_dotenv(local_path, override=True)

    for key, value in _LOCAL_DEFAULTS.items():
        if not local_values.get(key):
            os.environ[key] = value

    # The repository-root .env belongs to Docker. Share only administrator
    # bootstrap values with local development, never DB/Cookie/CORS settings.
    root_values = dotenv_values(project_root / ".env")
    for key in _SHARED_ADMIN_KEYS:
        if not local_values.get(key) and root_values.get(key):
            os.environ[key] = str(root_values[key])
    return True
