import json
import threading
from auth.context import user_data_path

_LOCK = threading.RLock()


def _notes_file():
    return user_data_path("imported_notes.json")


def _load() -> list[dict]:
    notes_file = _notes_file()
    notes_file.parent.mkdir(parents=True, exist_ok=True)
    if not notes_file.exists():
        return []
    return json.loads(notes_file.read_text(encoding="utf-8"))


def _save(notes: list[dict]) -> None:
    notes_file = _notes_file()
    notes_file.parent.mkdir(parents=True, exist_ok=True)
    temp = notes_file.with_suffix(".tmp")
    temp.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(notes_file)


def add_note(note: dict) -> None:
    with _LOCK:
        notes = _load()
        notes = [n for n in notes if n.get("id") != note["id"]]
        notes.insert(0, note)
        _save(notes)


def list_notes() -> list[dict]:
    with _LOCK:
        return _load()


def get_note(note_id: str) -> dict | None:
    return next((n for n in _load() if n.get("id") == note_id), None)


def delete_note(note_id: str) -> bool:
    with _LOCK:
        notes = _load()
        filtered = [n for n in notes if n.get("id") != note_id]
        if len(filtered) == len(notes):
            return False
        _save(filtered)
        return True
