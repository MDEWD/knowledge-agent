import json
from config import DATA_PATH

_NOTES_FILE = DATA_PATH / "imported_notes.json"


def _load() -> list[dict]:
    _NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _NOTES_FILE.exists():
        return []
    return json.loads(_NOTES_FILE.read_text(encoding="utf-8"))


def _save(notes: list[dict]) -> None:
    _NOTES_FILE.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")


def add_note(note: dict) -> None:
    notes = _load()
    notes = [n for n in notes if n.get("id") != note["id"]]
    notes.insert(0, note)
    _save(notes)


def list_notes() -> list[dict]:
    return _load()


def get_note(note_id: str) -> dict | None:
    return next((n for n in _load() if n.get("id") == note_id), None)


def delete_note(note_id: str) -> bool:
    notes = _load()
    filtered = [n for n in notes if n.get("id") != note_id]
    if len(filtered) == len(notes):
        return False
    _save(filtered)
    return True
