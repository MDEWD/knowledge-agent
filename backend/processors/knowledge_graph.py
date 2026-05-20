import json
import re

from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, DATA_PATH
from storage.video_db import list_videos

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

_CACHE_FILE = DATA_PATH / "graph_concepts.json"


def _load_cache() -> dict:
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _CACHE_FILE.exists():
        return {}
    return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))


def _save_cache(cache: dict) -> None:
    _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_concepts(video: dict, cache: dict) -> list[str]:
    vid_id = video.get("id", "")
    if vid_id in cache:
        return cache[vid_id]

    insights = video.get("insights", "") or video.get("summary", "")
    if not insights:
        cache[vid_id] = []
        return []

    try:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            max_tokens=150,
            messages=[
                {"role": "system", "content": "只输出JSON数组，不要任何解释。"},
                {
                    "role": "user",
                    "content": (
                        "从以下文本中提取3-6个最核心的知识概念或主题词（2-8字）。\n"
                        '输出格式：["概念1", "概念2", ...]\n\n'
                        f"{insights[:1500]}"
                    ),
                },
            ],
        )
        raw = resp.choices[0].message.content or "[]"
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        concepts = json.loads(match.group()) if match else []
    except Exception:
        concepts = []

    cache[vid_id] = [str(c).strip() for c in concepts[:6] if c]
    return cache[vid_id]


def build_graph(force_rebuild: bool = False) -> dict:
    videos = list_videos()
    if not videos:
        return {"nodes": [], "edges": []}

    cache = {} if force_rebuild else _load_cache()
    concept_videos: dict[str, list[str]] = {}
    video_concepts: dict[str, list[str]] = {}

    for v in videos:
        concepts = _extract_concepts(v, cache)
        video_concepts[v["id"]] = concepts
        for c in concepts:
            concept_videos.setdefault(c, []).append(v["id"])

    _save_cache(cache)

    nodes: list[dict] = []
    for v in videos:
        nodes.append(
            {
                "id": f"v_{v['id']}",
                "label": v.get("title", "Unknown"),
                "type": "video",
                "category": v.get("category", "其他"),
                "url": v.get("url", ""),
                "video_id": v["id"],
            }
        )

    # Only include concept nodes shared by 2+ videos to reduce clutter
    shared_concepts = {c for c, vids in concept_videos.items() if len(vids) >= 2}
    for concept in shared_concepts:
        nodes.append(
            {
                "id": f"c_{concept}",
                "label": concept,
                "type": "concept",
                "category": "概念",
                "shared_count": len(concept_videos[concept]),
            }
        )

    concept_node_ids = {n["id"] for n in nodes if n["type"] == "concept"}
    edges: list[dict] = []
    edge_set: set[str] = set()

    for v in videos:
        for concept in video_concepts.get(v["id"], []):
            cid = f"c_{concept}"
            if cid not in concept_node_ids:
                continue
            eid = f"v_{v['id']}__{cid}"
            if eid not in edge_set:
                edge_set.add(eid)
                edges.append({"source": f"v_{v['id']}", "target": cid, "type": "mentions"})

    for v in videos:
        for rid in v.get("related_ids") or []:
            a, b = sorted([v["id"], rid])
            eid = f"v_{a}__v_{b}"
            if eid not in edge_set:
                edge_set.add(eid)
                edges.append({"source": f"v_{a}", "target": f"v_{b}", "type": "related"})

    return {"nodes": nodes, "edges": edges}
