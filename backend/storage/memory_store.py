import json
from config import DATA_PATH

_MEMORY_FILE = DATA_PATH / "user_memory.json"

_DEFAULT: dict = {
    "interests": [],
    "learning_goals": [],
    "gaps": [],
    "key_insights": [],
    "summary": "",
    "updated_at": "",
}


def load() -> dict:
    _MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _MEMORY_FILE.exists():
        return dict(_DEFAULT)
    return json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))


def save(mem: dict) -> None:
    _MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


def reset() -> dict:
    mem = dict(_DEFAULT)
    save(mem)
    return mem
