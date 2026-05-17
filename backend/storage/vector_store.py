import hashlib
from typing import Optional
import chromadb
from chromadb.utils import embedding_functions
from config import CHROMA_DB_PATH, EMBED_MODEL

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


def add_document(insights: str, metadata: dict) -> None:
    col = _get_collection()
    chunks = [p.strip() for p in insights.split("\n\n") if len(p.strip()) > 40]

    ids, docs, metas = [], [], []
    for i, chunk in enumerate(chunks):
        doc_id = hashlib.md5(f"{metadata['url']}_{i}".encode()).hexdigest()
        ids.append(doc_id)
        docs.append(chunk)
        metas.append({
            "title": metadata.get("title", ""),
            "url": metadata.get("url", ""),
            "channel": metadata.get("channel", ""),
            "platform": metadata.get("platform", ""),
            "video_id": metadata.get("id", ""),
            "chunk_index": i,
        })

    col.upsert(ids=ids, documents=docs, metadatas=metas)


def search(query: str, n_results: int = 6) -> list[dict]:
    col = _get_collection()
    try:
        results = col.query(query_texts=[query], n_results=n_results)
    except Exception:
        return []

    items = []
    seen_titles = set()
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        items.append({"content": doc, "metadata": meta})
        seen_titles.add(meta.get("title", ""))
    return items


def delete_document(video_url: str) -> None:
    col = _get_collection()
    results = col.get(where={"url": video_url})
    if results["ids"]:
        col.delete(ids=results["ids"])
