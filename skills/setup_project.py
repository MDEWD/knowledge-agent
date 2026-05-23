#!/usr/bin/env python3
"""
One-click project setup — works on macOS, Linux, and Windows.

Usage:
    python skills/setup_project.py          # interactive (recommended)
    python skills/setup_project.py --skip-frontend
    python skills/setup_project.py --skip-env
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


# ── Constants ─────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR  = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
VENV_DIR     = BACKEND_DIR / ".venv"

IS_WINDOWS = platform.system() == "Windows"
PYTHON_BIN = str(VENV_DIR / ("Scripts/python.exe" if IS_WINDOWS else "bin/python"))
PIP_BIN    = str(VENV_DIR / ("Scripts/pip.exe"    if IS_WINDOWS else "bin/pip"))

RESET = "\033[0m"
BOLD  = "\033[1m"
GREEN = "\033[32m"
CYAN  = "\033[36m"
YELLOW = "\033[33m"
RED   = "\033[31m"

def c(color: str, text: str) -> str:
    if IS_WINDOWS and "TERM" not in os.environ:
        return text
    return f"{color}{text}{RESET}"

def step(msg: str):  print(c(CYAN,  f"\n▶  {msg}"))
def ok(msg: str):    print(c(GREEN, f"   ✓  {msg}"))
def warn(msg: str):  print(c(YELLOW,f"   ⚠  {msg}"))
def err(msg: str):   print(c(RED,   f"   ✗  {msg}"))
def info(msg: str):  print(f"      {msg}")
def hr():            print(c(CYAN, "─" * 55))


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list[str], cwd: Path | None = None, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd,
        capture_output=capture,
        text=True,
    )


def check_command(name: str) -> str | None:
    return shutil.which(name)


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"      {prompt}{suffix}: ").strip()
        return val if val else default
    except (EOFError, KeyboardInterrupt):
        return default


def ask_password(prompt: str) -> str:
    import getpass
    try:
        return getpass.getpass(f"      {prompt}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


# ── Checks ────────────────────────────────────────────────────────────────────

def check_python() -> str:
    step("Checking Python version")
    ver = sys.version_info
    if ver < (3, 11):
        err(f"Python 3.11+ required, found {ver.major}.{ver.minor}")
        info("Download: https://www.python.org/downloads/")
        sys.exit(1)
    ok(f"Python {ver.major}.{ver.minor}.{ver.micro}")
    return sys.executable


def check_node():
    step("Checking Node.js")
    node = check_command("node")
    if not node:
        err("Node.js not found")
        if IS_WINDOWS:
            info("Download: https://nodejs.org/en/download/")
        else:
            info("Install: brew install node  OR  https://nodejs.org/")
        sys.exit(1)
    result = run(["node", "--version"], capture=True)
    ver_str = result.stdout.strip().lstrip("v")
    major = int(ver_str.split(".")[0]) if ver_str else 0
    if major < 18:
        err(f"Node.js 18+ required, found {ver_str}")
        sys.exit(1)
    ok(f"Node.js v{ver_str}")

    npm = check_command("npm")
    if not npm:
        err("npm not found (should come with Node.js)")
        sys.exit(1)
    ok("npm found")


def check_ffmpeg():
    step("Checking ffmpeg (required for Whisper audio transcription)")
    if check_command("ffmpeg"):
        result = run(["ffmpeg", "-version"], capture=True)
        ver_line = result.stdout.splitlines()[0] if result.stdout else "unknown"
        ok(f"ffmpeg found ({ver_line.split(' ')[2] if len(ver_line.split()) > 2 else 'ok'})")
    else:
        warn("ffmpeg not found — Whisper fallback transcription will not work")
        if IS_WINDOWS:
            info("Install: winget install ffmpeg   OR   choco install ffmpeg")
            info("Or download from https://ffmpeg.org/download.html")
        elif platform.system() == "Darwin":
            info("Install: brew install ffmpeg")
        else:
            info("Install: sudo apt install ffmpeg")
        info("(You can continue without it — only needed for videos without subtitles)")


# ── Backend setup ─────────────────────────────────────────────────────────────

def create_venv():
    step("Creating Python virtual environment")
    if VENV_DIR.exists():
        ok(f"Venv already exists at {VENV_DIR.relative_to(PROJECT_ROOT)}")
        return
    result = run([sys.executable, "-m", "venv", str(VENV_DIR)])
    if result.returncode != 0:
        err("Failed to create venv")
        sys.exit(1)
    ok(f"Created venv at {VENV_DIR.relative_to(PROJECT_ROOT)}")


def install_requirements():
    step("Installing Python dependencies")
    req = BACKEND_DIR / "requirements.txt"
    if not req.exists():
        err(f"requirements.txt not found at {req}")
        sys.exit(1)
    info("This may take a few minutes on first run (downloading ML models)…")
    result = run([PIP_BIN, "install", "-r", str(req), "--quiet"])
    if result.returncode != 0:
        err("pip install failed — check output above")
        sys.exit(1)
    ok("All Python packages installed")


# ── .env setup ────────────────────────────────────────────────────────────────

def _write_env(values: dict[str, str]):
    env_path = BACKEND_DIR / ".env"
    lines = []
    example = BACKEND_DIR / ".env.example"
    if example.exists():
        # Preserve comments and structure from .env.example
        for line in example.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped == "":
                lines.append(line)
                continue
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                val = values.get(key, stripped.split("=", 1)[1].strip())
                lines.append(f"{key}={val}")
            else:
                lines.append(line)
    else:
        for k, v in values.items():
            lines.append(f"{k}={v}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def setup_env(skip: bool):
    step("Configuring environment (.env)")
    env_path = BACKEND_DIR / ".env"

    if skip:
        if env_path.exists():
            ok(".env already exists — skipped (--skip-env)")
        else:
            warn(".env not found; copy backend/.env.example → backend/.env and fill in keys")
        return

    if env_path.exists():
        overwrite = ask("backend/.env already exists. Overwrite? (y/N)", "N").lower()
        if overwrite != "y":
            ok(".env kept unchanged")
            return

    print()
    print(c(BOLD, "   Configure API keys (press Enter to skip optional keys)"))
    print()

    # Required
    print(c(YELLOW, "   ── Required ──────────────────────────────────"))
    deepseek_key = ask_password("DeepSeek API key  (get at platform.deepseek.com)")
    if not deepseek_key:
        warn("No DeepSeek key entered — you can add it to backend/.env later")
        deepseek_key = "your_deepseek_api_key_here"

    # Obsidian vault
    print()
    print(c(YELLOW, "   ── Obsidian vault path ──────────────────────"))
    if IS_WINDOWS:
        default_vault = r"C:\Users\YourName\Documents\MyKnowledge\Videos"
    else:
        home = Path.home()
        default_vault = str(home / "Documents" / "MyKnowledge" / "Videos")
    obsidian_vault = ask("Obsidian vault folder (leave blank to set later)", default_vault)

    # Optional
    print()
    print(c(YELLOW, "   ── Optional ──────────────────────────────────"))
    qwen_key = ask_password("Qwen (通义千问) API key  (optional, press Enter to skip)")

    langfuse_pub = ask("LangFuse public key  (optional, press Enter to skip)")
    langfuse_sec = ""
    if langfuse_pub:
        langfuse_sec = ask_password("LangFuse secret key")

    values = {
        "DEEPSEEK_API_KEY":    deepseek_key,
        "DEEPSEEK_BASE_URL":   "https://api.deepseek.com",
        "DEEPSEEK_MODEL":      "deepseek-chat",
        "QWEN_API_KEY":        qwen_key or "your_qwen_api_key_here",
        "QWEN_BASE_URL":       "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "QWEN_MODEL":          "qwen-plus",
        "OBSIDIAN_VAULT":      obsidian_vault,
        "LANGFUSE_PUBLIC_KEY": langfuse_pub or "",
        "LANGFUSE_SECRET_KEY": langfuse_sec or "",
        "LANGFUSE_BASE_URL":   "https://cloud.langfuse.com",
    }
    _write_env(values)
    ok(f"Written to {env_path.relative_to(PROJECT_ROOT)}")


# ── Frontend setup ────────────────────────────────────────────────────────────

def install_frontend(skip: bool):
    step("Installing frontend dependencies")
    if skip:
        info("Skipped (--skip-frontend)")
        return
    if not FRONTEND_DIR.exists():
        warn(f"frontend/ directory not found at {FRONTEND_DIR}")
        return
    result = run(["npm", "install", "--silent"], cwd=FRONTEND_DIR)
    if result.returncode != 0:
        err("npm install failed")
        sys.exit(1)
    ok("Frontend packages installed")


# ── Obsidian vault creation helper ────────────────────────────────────────────

def ensure_obsidian_vault():
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return
    vault_path: Path | None = None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("OBSIDIAN_VAULT="):
            val = line.split("=", 1)[1].strip()
            if val and "your" not in val.lower():
                vault_path = Path(val)
            break
    if not vault_path:
        return
    step("Checking Obsidian vault directory")
    if vault_path.exists():
        ok(f"Vault exists at {vault_path}")
    else:
        create = ask(f"Vault directory not found. Create {vault_path}? (Y/n)", "Y").lower()
        if create != "n":
            vault_path.mkdir(parents=True, exist_ok=True)
            ok(f"Created {vault_path}")
        else:
            warn(f"Vault not created — update OBSIDIAN_VAULT in backend/.env before running")


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary():
    hr()
    print(c(GREEN, c(BOLD, "\n   Setup complete! 🎉\n")))

    activate = (
        r"backend\.venv\Scripts\activate"
        if IS_WINDOWS else
        "source backend/.venv/bin/activate"
    )

    print(c(BOLD, "   Start the backend:"))
    info(f"{activate}")
    info("python backend/app.py")
    print()
    print(c(BOLD, "   Start the frontend (separate terminal):"))
    info("cd frontend && npm run dev")
    print()
    print(c(BOLD, "   Open in browser:"))
    info("http://localhost:5173")
    print()
    print(c(BOLD, "   MCP server for Claude Desktop / Cursor:"))
    info("See README.md → MCP section for claude_desktop_config.json")
    hr()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="One-click project setup")
    parser.add_argument("--skip-frontend", action="store_true", help="Skip npm install")
    parser.add_argument("--skip-env",      action="store_true", help="Skip .env creation")
    args = parser.parse_args()

    hr()
    print(c(BOLD, c(CYAN, "   Personal Video Knowledge Base — Project Setup")))
    hr()
    info(f"Platform : {platform.system()} {platform.machine()}")
    info(f"Python   : {sys.version.split()[0]}")
    info(f"Root dir : {PROJECT_ROOT}")

    check_python()
    check_node()
    check_ffmpeg()
    create_venv()
    install_requirements()
    setup_env(skip=args.skip_env)
    ensure_obsidian_vault()
    install_frontend(skip=args.skip_frontend)
    print_summary()


if __name__ == "__main__":
    main()
