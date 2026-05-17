import os
from pathlib import Path

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

OBSIDIAN_VAULT_PATH = Path(
    os.environ.get("OBSIDIAN_VAULT", str(Path.home() / "obsidian-vault" / "Videos"))
)
CHROMA_DB_PATH = Path(os.environ.get("CHROMA_DB_PATH", "./data/chroma_db"))
DATA_PATH = Path(os.environ.get("DATA_PATH", "./data"))

EMBED_MODEL = os.environ.get(
    "EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")
MAX_TRANSCRIPT_CHARS = int(os.environ.get("MAX_TRANSCRIPT_CHARS", "80000"))
