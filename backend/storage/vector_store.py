import hashlib
import re
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

from config import CHROMA_DB_PATH, EMBED_MODEL
from storage import bm25_store

_collection: Optional[chromadb.Collection] = None


def _get_collection() -> chromadb.Collection:
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBED_MODEL
        )
        _collection = client.get_or_create_collection(
            "knowledge_base", embedding_function=ef
        )
    return _collection


# ── Write ─────────────────────────────────────────────────────────────────────

def add_document(insights: str, metadata: dict) -> None:
    col = _get_collection()
    chunks = [p.strip() for p in insights.split("\n\n") if len(p.strip()) > 40]

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
    """Index note text with sentence-aware chunking (~500 chars per chunk)."""
    col = _get_collection()

    # Split on Chinese/English sentence endings, keeping the delimiter
    raw = re.split(r'(?<=[。！？.!?])\s*', text)
    chunks: list[str] = []
    current = ""
    for sent in raw:
        sent = sent.strip()
        if not sent:
            continue
        if len(current) + len(sent) + 1 <= 500:
            current = (current + " " + sent).strip()
        else:
            if len(current) > 30:
                chunks.append(current)
            current = sent
    if len(current) > 30:
        chunks.append(current)

    if not chunks:
        return

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
    col = _get_collection()
    candidate_n = min(n_results * 3, 20)

    # Dense (semantic) search
    dense_items: list[dict] = []
    try:
        results = col.query(query_texts=[query], n_results=candidate_n)
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            dense_items.append({"content": doc, "metadata": meta})
    except Exception:
        pass

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
