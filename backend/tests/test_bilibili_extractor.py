from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_importing_app_extractor_does_not_initialize_bilibili_network_runtime():
    """Unused Bilibili support must not register SDK atexit callbacks."""
    backend_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import extractors.bilibili; "
                "print('bilibili_api' in sys.modules)"
            ),
        ],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "False"
    assert "Event loop is closed" not in result.stderr
