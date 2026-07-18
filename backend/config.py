import os
from pathlib import Path

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

QWEN_API_KEY = os.environ.get("QWEN_API_KEY", "")
QWEN_BASE_URL = os.environ.get("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen-plus")

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

# LangFuse observability — gracefully absent if keys not set
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_BASE_URL = os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
