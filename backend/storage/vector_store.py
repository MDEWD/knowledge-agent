import hashlib
import logging
import re
import threading
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

from config import CHROMA_DB_PATH, EMBED_LOCAL_FILES_ONLY, EMBED_MODEL
from storage import bm25_store

logger = logging.getLogger(__name__)

_collection: Optional[chromadb.Collection] = None
_client = None
_embedding_function = None
_init_lock = threading.Lock()


def _get_collection() -> chromadb.Collection:
    global _client, _collection, _embedding_function
    if _collection is None:
        with _init_lock:
            if _collection is None:
                # On Windows, initialize Chroma's Rust runtime before loading
                # PyTorch/SentenceTransformer to avoid a native DLL access
                # violation. Cache each completed stage so a later retry does
                # not register a second client for the same persistence path.
                if _client is None:
                    _client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
                if _embedding_function is None:
                    _embedding_function = (
                        embedding_functions.SentenceTransformerEmbeddingFunction(
                        model_name=EMBED_MODEL,
                        local_files_only=EMBED_LOCAL_FILES_ONLY,
                        )
                    )
                _collection = _client.get_or_create_collection(
                    "knowledge_base", embedding_function=_embedding_function
                )
    return _collection


# ── Write ─────────────────────────────────────────────────────────────────────

def add_document(insights: str, metadata: dict) -> None:
    col = _get_collection()
    paras = [p.strip() for p in insights.split("\n\n") if len(p.strip()) > 40]

    # Add one-paragraph overlap: prefix each chunk with the tail of the previous one
    chunks = []
    for i, para in enumerate(paras):
        if i > 0:
            chunks.append(paras[i - 1][-200:] + "\n\n" + para)
        else:
            chunks.append(para)

    ids, docs, metas, bm25_items = [], [], [], []
    for i, chunk in enumerate(chunks):
        doc_id = hashlib.md5(f"{metadata['url']}_{i}".encode()).hexdigest()
        chunk_meta = {
            "title": metadata.get("title", ""),
            "url": metadata.get("url", ""),
            "channel": metadata.get("channel", ""),
            "platform": metadata.get("platform", ""),
            "video_id": metadata.get("id", ""),
            "chunk_index": i,
        }
        ids.append(doc_id)
        docs.append(chunk)
        metas.append(chunk_meta)
        bm25_items.append({"id": doc_id, "text": chunk, "metadata": chunk_meta})

    col.upsert(ids=ids, documents=docs, metadatas=metas)
    bm25_store.add_documents(bm25_items)


def add_note_document(text: str, metadata: dict) -> None:
    """Index note text with sentence-aware chunking (~500 chars, 1-sentence overlap)."""
    col = _get_collection()

    # Split on Chinese/English sentence endings
    raw = re.split(r'(?<=[。！？.!?])\s*', text)
    sentences = [s.strip() for s in raw if s.strip()]

    # Group sentences into ~500-char chunks
    sent_groups: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    for sent in sentences:
        if current_len + len(sent) + 1 <= 500:
            current.append(sent)
            current_len += len(sent) + 1
        else:
            if current_len > 30:
                sent_groups.append(current)
            current = [sent]
            current_len = len(sent)
    if current_len > 30:
        sent_groups.append(current)

    if not sent_groups:
        return

    # Build chunks with 1-sentence overlap from the previous group
    chunks = []
    for i, group in enumerate(sent_groups):
        if i > 0 and sent_groups[i - 1]:
            overlap = sent_groups[i - 1][-1]  # last sentence of previous chunk
            chunks.append(overlap + " " + " ".join(group))
        else:
            chunks.append(" ".join(group))

    ids, docs, metas, bm25_items = [], [], [], []
    for i, chunk in enumerate(chunks):
        doc_id = hashlib.md5(f"{metadata['url']}_{i}".encode()).hexdigest()
        chunk_meta = {
            "title": metadata.get("title", ""),
            "url": metadata.get("url", ""),
            "channel": metadata.get("channel", ""),
            "platform": metadata.get("platform", ""),
            "video_id": metadata.get("id", ""),
            "chunk_index": i,
        }
        ids.append(doc_id)
        docs.append(chunk)
        metas.append(chunk_meta)
        bm25_items.append({"id": doc_id, "text": chunk, "metadata": chunk_meta})

    col.upsert(ids=ids, documents=docs, metadatas=metas)
    bm25_store.add_documents(bm25_items)


def delete_document(video_url: str) -> None:
    col = _get_collection()
    results = col.get(where={"url": video_url})
    if results["ids"]:
        col.delete(ids=results["ids"])
    bm25_store.delete_by_url(video_url)


# ── Hybrid search with RRF ────────────────────────────────────────────────────

def _rrf_fuse(
    dense: list[dict],
    sparse: list[dict],
    k: int = 60,
    n: int = 6,
) -> list[dict]:
    """
    Reciprocal Rank Fusion of two ranked result lists.
    Key: url + chunk_index uniquely identifies a chunk in both indexes.
    """
    all_docs: dict[str, dict] = {}
    scores: dict[str, float] = {}

    def _key(item: dict) -> str:
        m = item["metadata"]
        return f"{m.get('url','')}::{m.get('chunk_index', 0)}"

    for rank, item in enumerate(dense):
        k_ = _key(item)
        all_docs[k_] = item
        scores[k_] = scores.get(k_, 0.0) + 1.0 / (k + rank + 1)

    for rank, item in enumerate(sparse):
        k_ = _key(item)
        if k_ not in all_docs:
            all_docs[k_] = item
        scores[k_] = scores.get(k_, 0.0) + 1.0 / (k + rank + 1)

    fused_keys = sorted(all_docs, key=lambda x: -scores[x])
    return [all_docs[k_] for k_ in fused_keys[:n]]


def search(query: str, n_results: int = 6) -> list[dict]:
    candidate_n = min(n_results * 3, 20)

    # Dense (semantic) search
    dense_items: list[dict] = []
    try:
        col = _get_collection()
        results = col.query(query_texts=[query], n_results=candidate_n)
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            dense_items.append({"content": doc, "metadata": meta})
    except Exception as exc:
        # Dense retrieval is optional for reads. Keep research available via
        # BM25 when Chroma or the local embedding model is temporarily down.
        logger.warning("Dense search unavailable; falling back to BM25: %s", exc)

    # Sparse (BM25) search
    sparse_items: list[dict] = []
    for doc_id, _ in bm25_store.search(query, n=candidate_n):
        doc = bm25_store.get_doc_by_id(doc_id)
        if doc:
            sparse_items.append({"content": doc["text"], "metadata": doc["metadata"]})

    # Fallback: BM25 not yet populated (e.g. fresh install before sync)
    if not sparse_items:
        return dense_items[:n_results]

    return _rrf_fuse(dense_items, sparse_items, n=n_results)


# ── Relevance gate ────────────────────────────────────────────────────────────

def is_topic_covered(query: str, min_chunks: int = 2, max_distance: float = 1.0) -> bool:
    """
    Return True only if KB contains at least `min_chunks` chunks genuinely
    related to `query`.

    ChromaDB uses L2 distance on normalised embeddings.
    L2 = sqrt(2*(1-cosine_sim)), so:
      L2 < 1.0  →  cosine_sim > 0.5   (moderately relevant)
      L2 < 0.77 →  cosine_sim > 0.7   (highly relevant)

    Unrelated topics (e.g. "AI Agent" vs economics corpus) typically score
    L2 > 1.2, so they are correctly rejected.
    """
    col = _get_collection()
    try:
        results = col.query(
            query_texts=[query],
            n_results=min_chunks,
            include=["distances"],
        )
        distances = results["distances"][0] if results["distances"] else []
        return sum(1 for d in distances if d <= max_distance) >= min_chunks
    except Exception:
        return False


# ── Related videos (dense only — title similarity doesn't benefit from BM25) ──

def find_related(video_id: str, title: str, n: int = 3) -> list[dict]:
    col = _get_collection()
    try:
        results = col.query(query_texts=[title], n_results=min(n * 4, 20))
    except Exception:
        return []

    seen_ids: set[str] = set()
    related: list[dict] = []
    for meta in results["metadatas"][0]:
        vid = meta.get("video_id", "")
        if vid and vid != video_id and vid not in seen_ids:
            seen_ids.add(vid)
            related.append({"id": vid, "title": meta.get("title", ""), "url": meta.get("url", "")})
            if len(related) >= n:
                break
    return related
