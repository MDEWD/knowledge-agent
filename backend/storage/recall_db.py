import json
from datetime import date
from config import DATA_PATH

_CARDS_FILE = DATA_PATH / "recall_cards.json"


def _load() -> list[dict]:
    _CARDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _CARDS_FILE.exists():
        return []
    return json.loads(_CARDS_FILE.read_text(encoding="utf-8"))


def _save(cards: list[dict]) -> None:
    _CARDS_FILE.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")


def add_cards(new_cards: list[dict]) -> None:
    cards = _load()
    existing_ids = {c["id"] for c in cards}
    cards.extend(c for c in new_cards if c["id"] not in existing_ids)
    _save(cards)


def list_cards(video_id: str | None = None) -> list[dict]:
    cards = _load()
    if video_id:
        cards = [c for c in cards if c.get("video_id") == video_id]
    return cards


def get_due_cards(limit: int = 30) -> list[dict]:
    today = date.today().isoformat()
    return [c for c in _load() if c.get("next_review", "9999-99-99") <= today][:limit]


def update_card(card_id: str, updates: dict) -> bool:
    cards = _load()
    for c in cards:
        if c["id"] == card_id:
            c.update(updates)
            _save(cards)
            return True
    return False


def delete_by_video(video_id: str) -> int:
    cards = _load()
    before = len(cards)
    cards = [c for c in cards if c.get("video_id") != video_id]
    _save(cards)
    return before - len(cards)


def get_stats() -> dict:
    today = date.today().isoformat()
    cards = _load()
    due = sum(1 for c in cards if c.get("next_review", "9999") <= today)
    mastered = sum(1 for c in cards if c.get("repetitions", 0) >= 3 and c.get("ease_factor", 2.5) >= 2.0)
    return {
        "total": len(cards),
        "due_today": due,
        "mastered": mastered,
        "learning": len(cards) - mastered,
    }
