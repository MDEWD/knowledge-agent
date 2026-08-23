import os
from pathlib import Path

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

QWEN_API_KEY = os.environ.get("QWEN_API_KEY", "")
QWEN_BASE_URL = os.environ.get("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen-plus")

OBSIDIAN_VAULT_PATH = Path(
    os.environ.get("OBSIDIAN_VAULT", str(Path.home() / "obsidian-vault" / "Videos"))
)
CHROMA_DB_PATH = Path(os.environ.get("CHROMA_DB_PATH", "./data/chroma_db"))
DATA_PATH = Path(os.environ.get("DATA_PATH", "./data"))
UVICORN_RELOAD = os.environ.get("UVICORN_RELOAD", "false").lower() in {
    "1", "true", "yes", "on",
}

# MySQL business persistence. When a password is configured, memory/history
# stores default to MySQL; development and tests without credentials retain the
# file-backed fallback.
MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "multi_agent_platform")
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_POOL_SIZE = int(os.environ.get("MYSQL_POOL_SIZE", "5"))
DEFAULT_USER_ID = os.environ.get("DEFAULT_USER_ID", "local-user")

# Email authentication. The development fallback keeps local setup simple, but
# production deployments must provide a long random AUTH_SECRET_KEY.
AUTH_SECRET_KEY = os.environ.get(
    "AUTH_SECRET_KEY",
    "dev-only-change-this-secret-before-production-please",
)
AUTH_JWT_ALGORITHM = os.environ.get("AUTH_JWT_ALGORITHM", "HS256")
AUTH_ACCESS_TOKEN_MINUTES = int(os.environ.get("AUTH_ACCESS_TOKEN_MINUTES", "30"))
AUTH_REFRESH_TOKEN_DAYS = int(os.environ.get("AUTH_REFRESH_TOKEN_DAYS", "14"))
AUTH_COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "false").lower() in {
    "1", "true", "yes", "on",
}
AUTH_COOKIE_SAMESITE = os.environ.get("AUTH_COOKIE_SAMESITE", "lax").lower()
if AUTH_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    AUTH_COOKIE_SAMESITE = "lax"
AUTH_ACCESS_COOKIE_NAME = os.environ.get("AUTH_ACCESS_COOKIE_NAME", "agent_access")
AUTH_REFRESH_COOKIE_NAME = os.environ.get("AUTH_REFRESH_COOKIE_NAME", "agent_refresh")
AUTH_CODE_MINUTES = int(os.environ.get("AUTH_CODE_MINUTES", "10"))
AUTH_CODE_RESEND_SECONDS = int(os.environ.get("AUTH_CODE_RESEND_SECONDS", "60"))
AUTH_CODE_MAX_ATTEMPTS = int(os.environ.get("AUTH_CODE_MAX_ATTEMPTS", "5"))
AUTH_EXPOSE_CODES = os.environ.get("AUTH_EXPOSE_CODES", "false").lower() in {
    "1", "true", "yes", "on",
}
AUTH_ADMIN_EMAILS = {
    value.strip().lower()
    for value in os.environ.get("AUTH_ADMIN_EMAILS", "").split(",")
    if value.strip()
}

# Optional bootstrap administrator, created at startup when both are set.
DEFAULT_ADMIN_EMAIL = os.environ.get("DEFAULT_ADMIN_EMAIL", "").strip().lower()
DEFAULT_ADMIN_PASSWORD = os.environ.get("DEFAULT_ADMIN_PASSWORD", "")

# SMTP is optional for local development. Without SMTP, verification codes are
# written to the backend terminal; production deployments should configure it.
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", SMTP_USERNAME)
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "知研 Agent")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() in {
    "1", "true", "yes", "on",
}
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "false").lower() in {
    "1", "true", "yes", "on",
}

# CORS: comma-separated allowed browser origins. Credentialed cookies mean
# wildcards are not allowed, so list every production origin explicitly.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",")
    if origin.strip()
]

# Production serves the built frontend from this directory when it exists.
FRONTEND_DIST_DIR = os.environ.get(
    "FRONTEND_DIST_DIR",
    str(Path(__file__).resolve().parent.parent / "frontend" / "dist"),
)

MEMORY_STORAGE_BACKEND = os.environ.get(
    "MEMORY_STORAGE_BACKEND",
    "mysql" if MYSQL_PASSWORD else "json",
).strip().lower()
MEMORY_REFLECTION_THRESHOLD = int(os.environ.get("MEMORY_REFLECTION_THRESHOLD", "50"))
MEMORY_OBSERVATION_TTL_DAYS = int(os.environ.get("MEMORY_OBSERVATION_TTL_DAYS", "30"))
MEMORY_INFERRED_TTL_DAYS = int(os.environ.get("MEMORY_INFERRED_TTL_DAYS", "180"))
MEMORY_RETRIEVAL_LIMIT = int(os.environ.get("MEMORY_RETRIEVAL_LIMIT", "12"))
MEMORY_CONTEXT_MAX_CHARS = int(os.environ.get("MEMORY_CONTEXT_MAX_CHARS", "3000"))

EMBED_MODEL = os.environ.get(
    "EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
EMBED_LOCAL_FILES_ONLY = os.environ.get(
    "EMBED_LOCAL_FILES_ONLY", "false"
).lower() in {"1", "true", "yes", "on"}
# Importing a large PDF must not force-load the native SentenceTransformer
# runtime. BM25 indexing remains available; enable this only on machines with
# enough memory and a working local embedding model.
NOTE_IMPORT_VECTOR_INDEX = os.environ.get(
    "NOTE_IMPORT_VECTOR_INDEX", "false"
).lower() in {"1", "true", "yes", "on"}
# Local SentenceTransformer/CrossEncoder models use native runtimes and can
# terminate memory-constrained Windows processes. BM25 remains the safe default.
LOCAL_RAG_MODELS_ENABLED = os.environ.get(
    "LOCAL_RAG_MODELS_ENABLED", "false"
).lower() in {"1", "true", "yes", "on"}
CHAT_TOOL_TIMEOUT_SECONDS = float(os.environ.get("CHAT_TOOL_TIMEOUT_SECONDS", "45"))
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")
MAX_TRANSCRIPT_CHARS = int(os.environ.get("MAX_TRANSCRIPT_CHARS", "80000"))

# LangFuse observability — gracefully absent if keys not set
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_BASE_URL = os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

# ── Deep Research (DeepResearch 项目融合) ──────────────────────────────────────
# 检索后端: kb_only / web_only / hybrid
#   kb_only  — 仅检索个人知识库(ChromaDB + BM25 + CrossEncoder)
#   web_only — 仅调用 Tavily 联网搜索
#   hybrid   — 同时检索知识库与联网,合并结果
SEARCH_BACKEND = os.environ.get("SEARCH_BACKEND", "kb_only")

# Tavily 配置(SEARCH_BACKEND 含 web 时必填)
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
TAVILY_BASE_URL = os.environ.get("TAVILY_BASE_URL", "https://api.tavily.com")
TAVILY_MAX_RESULTS = int(os.environ.get("TAVILY_MAX_RESULTS", "3"))
TAVILY_TOPIC = os.environ.get("TAVILY_TOPIC", "general")
TAVILY_TIMEOUT_SECONDS = int(os.environ.get("TAVILY_TIMEOUT_SECONDS", "60"))
TAVILY_LLM_SUMMARIZE = os.environ.get("TAVILY_LLM_SUMMARIZE", "false").lower() in {
    "1", "true", "yes", "on",
}

# China public-fund research (public web evidence)
CN_FUND_ENABLE_WEB_SEARCH = os.environ.get("CN_FUND_ENABLE_WEB_SEARCH", "true").lower() == "true"
CN_FUND_ANNUAL_RISK_FREE_RATE = float(os.environ.get("CN_FUND_ANNUAL_RISK_FREE_RATE", "0.015"))
CN_FUND_DEFAULT_BENCHMARK = os.environ.get("CN_FUND_DEFAULT_BENCHMARK", "")

# Deep Research 迭代与对抗预算
DEEP_RESEARCH_MAX_ITERATIONS = int(os.environ.get("DEEP_RESEARCH_MAX_ITERATIONS", "15"))
DEEP_RESEARCH_MAX_CONCURRENT = int(os.environ.get("DEEP_RESEARCH_MAX_CONCURRENT", "2"))
DEEP_RESEARCH_MIN_REPAIR_SCORE = float(os.environ.get("DEEP_RESEARCH_MIN_REPAIR_SCORE", "6.0"))
DEEP_RESEARCH_RED_TEAM_MAX = int(os.environ.get("DEEP_RESEARCH_RED_TEAM_MAX", "3"))
DEEP_RESEARCH_SUB_MAX_STEPS = int(os.environ.get("DEEP_RESEARCH_SUB_MAX_STEPS", "5"))
DEEP_RESEARCH_RESEARCHER_MAIN_API = os.environ.get(
    "DEEP_RESEARCH_RESEARCHER_MAIN_API", "responses"
).strip().lower()
DEEP_RESEARCH_LLM_TIMEOUT_SECONDS = float(
    os.environ.get("DEEP_RESEARCH_LLM_TIMEOUT_SECONDS", "120")
)
DEEP_RESEARCH_LLM_RETRY_ATTEMPTS = int(
    os.environ.get("DEEP_RESEARCH_LLM_RETRY_ATTEMPTS", "5")
)
DEEP_RESEARCH_LLM_RETRY_BASE_SECONDS = float(
    os.environ.get("DEEP_RESEARCH_LLM_RETRY_BASE_SECONDS", "1")
)
DEEP_RESEARCH_LLM_RETRY_MAX_SECONDS = float(
    os.environ.get("DEEP_RESEARCH_LLM_RETRY_MAX_SECONDS", "12")
)
DEEP_RESEARCH_HTTP_MAX_CONNECTIONS = int(
    os.environ.get("DEEP_RESEARCH_HTTP_MAX_CONNECTIONS", "8")
)
DEEP_RESEARCH_HTTP_KEEPALIVE_CONNECTIONS = int(
    os.environ.get("DEEP_RESEARCH_HTTP_KEEPALIVE_CONNECTIONS", "0")
)
DEEP_RESEARCH_EVALUATOR_MAX_TOKENS = int(
    os.environ.get("DEEP_RESEARCH_EVALUATOR_MAX_TOKENS", "2048")
)
DEEP_RESEARCH_FINAL_MAX_TOKENS = int(
    os.environ.get("DEEP_RESEARCH_FINAL_MAX_TOKENS", "8192")
)
DEEP_RESEARCH_FINAL_MAX_CONTINUATIONS = int(
    os.environ.get("DEEP_RESEARCH_FINAL_MAX_CONTINUATIONS", "4")
)
DEEP_RESEARCH_MAX_INPUT_TOKENS = int(os.environ.get("DEEP_RESEARCH_MAX_INPUT_TOKENS", "240000000"))
DEEP_RESEARCH_MAX_OUTPUT_TOKENS = int(os.environ.get("DEEP_RESEARCH_MAX_OUTPUT_TOKENS", "600000000"))
DEEP_RESEARCH_MAX_TOOL_CALLS = int(os.environ.get("DEEP_RESEARCH_MAX_TOOL_CALLS", "200"))
DEEP_RESEARCH_MAX_COST_USD = float(os.environ.get("DEEP_RESEARCH_MAX_COST_USD", "0"))
DEEP_RESEARCH_FLASH_INPUT_PER_MILLION_USD = float(
    os.environ.get("DEEP_RESEARCH_FLASH_INPUT_PER_MILLION_USD", "0")
)
DEEP_RESEARCH_FLASH_OUTPUT_PER_MILLION_USD = float(
    os.environ.get("DEEP_RESEARCH_FLASH_OUTPUT_PER_MILLION_USD", "0")
)
DEEP_RESEARCH_PRO_INPUT_PER_MILLION_USD = float(
    os.environ.get("DEEP_RESEARCH_PRO_INPUT_PER_MILLION_USD", "0")
)
DEEP_RESEARCH_PRO_OUTPUT_PER_MILLION_USD = float(
    os.environ.get("DEEP_RESEARCH_PRO_OUTPUT_PER_MILLION_USD", "0")
)
