import json
import re
from pathlib import Path
from typing import Optional

from rank_bm25 import BM25Okapi
from config import DATA_PATH

_CORPUS_PATH = DATA_PATH / "bm25_corpus.json"

# In-memory state — rebuilt lazily from corpus file
_corpus: Optional[list[dict]] = None   # [{id, text, metadata}]
_index: Optional[BM25Okapi] = None
_tokenized_corpus: Optional[list[list[str]]] = None


# ── Tokenizer ─────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """
    Chinese-aware tokenizer.
    CJK characters: unigrams + bigrams (captures compound words without jieba).
    Latin/numeric: lowercase words.
    """
    tokens: list[str] = []
    for chunk in re.split(
        r'[\s，。！？；：""''【】《》、…—～　-〿＀-￯]+',
        text.lower(),
    ):
        if not chunk:
            continue
        if re.search(r'[一-鿿]', chunk):
            tokens.extend(list(chunk))                              # unigrams
            tokens.extend(chunk[i:i+2] for i in range(len(chunk) - 1))  # bigrams
        else:
            tokens.append(chunk)
    return [t for t in tokens if t]


# ── Corpus persistence ────────────────────────────────────────────────────────

def _load_corpus() -> list[dict]:
    global _corpus
    if _corpus is not None:
        return _corpus
    if _CORPUS_PATH.exists():
        try:
            _corpus = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            _corpus = []
    else:
        _corpus = []
    return _corpus


def _save_corpus() -> None:
    _CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CORPUS_PATH.write_text(
        json.dumps(_corpus, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _invalidate_index() -> None:
    global _index, _tokenized_corpus
    _index = None
    _tokenized_corpus = None


# ── Index access ──────────────────────────────────────────────────────────────

def _get_index() -> Optional[BM25Okapi]:
    global _index, _tokenized_corpus
    if _index is not None:
        return _index
    corpus = _load_corpus()
    if not corpus:
        return None
    _tokenized_corpus = [_tokenize(doc["text"]) for doc in corpus]
    _index = BM25Okapi(_tokenized_corpus)
    return _index


# ── Public API ────────────────────────────────────────────────────────────────

def add_documents(items: list[dict]) -> None:
    """Add list of {id, text, metadata} dicts. Skips IDs already present."""
    corpus = _load_corpus()
    existing_ids = {doc["id"] for doc in corpus}
    new_items = [item for item in items if item["id"] not in existing_ids]
    if not new_items:
        return
    corpus.extend(new_items)
    _save_corpus()
    _invalidate_index()


def delete_by_url(video_url: str) -> None:
    global _corpus
    corpus = _load_corpus()
    before = len(corpus)
    _corpus = [d for d in corpus if d.get("metadata", {}).get("url") != video_url]
    if len(_corpus) != before:
        _save_corpus()
        _invalidate_index()


def search(query: str, n: int = 12) -> list[tuple[str, float]]:
    """Return [(doc_id, bm25_score), ...] sorted descending. Only non-zero scores."""
    index = _get_index()
    if index is None:
        return []
    tokens = _tokenize(query)
    if not tokens:
        return []
    scores = index.get_scores(tokens)
    corpus = _load_corpus()
    ranked = sorted(
        ((corpus[i]["id"], float(score)) for i, score in enumerate(scores) if score > 0),
        key=lambda x: -x[1],
    )
    return ranked[:n]


def get_doc_by_id(doc_id: str) -> Optional[dict]:
    for doc in _load_corpus():
        if doc["id"] == doc_id:
            return doc
    return None


def corpus_size() -> int:
    return len(_load_corpus())
