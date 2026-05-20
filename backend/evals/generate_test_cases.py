"""
Auto-generate Q&A test cases from KB content using LLM.
Avoids manual labeling — samples real chunks and generates questions from them.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from openai import AsyncOpenAI
from config import DATA_PATH, DEEPSEEK_MODEL

_OUTPUT = DATA_PATH / "eval_cases.json"

_GEN_PROMPT = """\
根据以下知识库内容片段，生成一个高质量的问答测试用例。

要求：
- question: 一个具体、有意义的问题（用中文），能从该内容中找到答案
- ground_truth: 基于该内容的标准答案（2-4句话）
- chunk_id: 原始片段标识符（直接复制提供的 chunk_id）

以 JSON 格式返回（不要有任何其他内容）：
{"question": "...", "ground_truth": "...", "chunk_id": "..."}
"""


async def generate_test_cases(
    client: AsyncOpenAI,
    n: int = 10,
    force: bool = False,
) -> list[dict]:
    """Sample chunks from ChromaDB and generate Q&A test cases."""
    if _OUTPUT.exists() and not force:
        existing = json.loads(_OUTPUT.read_text(encoding="utf-8"))
        if existing:
            return existing

    from storage.vector_store import _get_collection
    col = _get_collection()

    # Get all documents
    try:
        all_docs = col.get(include=["documents", "metadatas"])
    except Exception:
        return []

    docs = all_docs.get("documents") or []
    metas = all_docs.get("metadatas") or []
    ids = all_docs.get("ids") or []

    if not docs:
        return []

    # Sample up to n unique chunks (prefer longer, more information-rich ones)
    candidates = [
        (id_, doc, meta)
        for id_, doc, meta in zip(ids, docs, metas)
        if len(doc) > 100
    ]
    sample = random.sample(candidates, min(n, len(candidates)))

    test_cases = []
    for chunk_id, doc, meta in sample:
        try:
            resp = await client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": _GEN_PROMPT},
                    {"role": "user", "content": f"chunk_id: {chunk_id}\n\n内容：\n{doc[:1500]}"},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            case = json.loads(resp.choices[0].message.content)
            case["source_title"] = meta.get("title", "")
            case["source_url"] = meta.get("url", "")
            case["context"] = doc
            test_cases.append(case)
        except Exception:
            continue

    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(json.dumps(test_cases, ensure_ascii=False, indent=2), encoding="utf-8")
    return test_cases
