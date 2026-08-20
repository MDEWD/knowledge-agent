"""Tenant-isolated BM25 persistence and in-memory indexes."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from typing import Optional

from rank_bm25 import BM25Okapi

from auth.context import get_current_user_id, user_data_path


@dataclass
class _State:
    corpus: list[dict] | None = None
    index: BM25Okapi | None = None
    tokenized: list[list[str]] | None = None


_states: dict[str, _State] = {}
_lock = threading.RLock()


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for chunk in re.split(
        r'[\s，。！？；：""\'\'【】《》、…—～　\u3000-\u303f\uff00-\uffef]+',
        text.lower(),
    ):
        if not chunk:
            continue
        if re.search(r'[\u4e00-\u9fff]', chunk):
            tokens.extend(list(chunk))
            tokens.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
        else:
            tokens.append(chunk)
    return [token for token in tokens if token]


def _state(user_id: str | None = None) -> tuple[str, _State]:
    uid = user_id or get_current_user_id()
    with _lock:
        return uid, _states.setdefault(uid, _State())


def _corpus_path(user_id: str):
    return user_data_path("bm25_corpus.json", user_id=user_id)


def _load_corpus(user_id: str, state: _State) -> list[dict]:
    if state.corpus is not None:
        return state.corpus
    path = _corpus_path(user_id)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            state.corpus = payload if isinstance(payload, list) else []
        except (OSError, json.JSONDecodeError):
            state.corpus = []
    else:
        state.corpus = []
    return state.corpus


def _save_corpus(user_id: str, state: _State) -> None:
    path = _corpus_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state.corpus or [], ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _invalidate(state: _State) -> None:
    state.index = None
    state.tokenized = None


def _get_index(user_id: str, state: _State) -> Optional[BM25Okapi]:
    if state.index is not None:
        return state.index
    corpus = _load_corpus(user_id, state)
    if not corpus:
        return None
    state.tokenized = [_tokenize(doc["text"]) for doc in corpus]
    state.index = BM25Okapi(state.tokenized)
    return state.index


def add_documents(items: list[dict]) -> None:
    user_id, state = _state()
    with _lock:
        corpus = _load_corpus(user_id, state)
        existing_ids = {doc["id"] for doc in corpus}
        new_items = []
        for item in items:
            if item["id"] in existing_ids:
                continue
            copy = dict(item)
            copy["metadata"] = {**dict(copy.get("metadata") or {}), "user_id": user_id}
            new_items.append(copy)
        if not new_items:
            return
        corpus.extend(new_items)
        _save_corpus(user_id, state)
        _invalidate(state)


def delete_by_url(video_url: str) -> None:
    user_id, state = _state()
    with _lock:
        corpus = _load_corpus(user_id, state)
        filtered = [doc for doc in corpus if doc.get("metadata", {}).get("url") != video_url]
        if len(filtered) == len(corpus):
            return
        state.corpus = filtered
        _save_corpus(user_id, state)
        _invalidate(state)


def search(query: str, n: int = 12) -> list[tuple[str, float]]:
    user_id, state = _state()
    with _lock:
        index = _get_index(user_id, state)
        if index is None:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = index.get_scores(tokens)
        corpus = _load_corpus(user_id, state)
        ranked = sorted(
            ((corpus[i]["id"], float(score)) for i, score in enumerate(scores) if score > 0),
            key=lambda item: -item[1],
        )
        return ranked[:n]


def get_doc_by_id(doc_id: str) -> Optional[dict]:
    user_id, state = _state()
    with _lock:
        return next((doc for doc in _load_corpus(user_id, state) if doc["id"] == doc_id), None)


def corpus_size() -> int:
    user_id, state = _state()
    with _lock:
        return len(_load_corpus(user_id, state))
