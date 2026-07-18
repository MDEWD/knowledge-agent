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


def analyze_gaps(graph_data: dict | None = None) -> dict:
    """
    Detect knowledge gaps in the graph:
    - Isolated nodes: videos with ≤ 1 connection (poorly integrated knowledge)
    - Unexpected connections: cross-category video-to-video edges (potential insights)
    - Missing topics: LLM-identified gaps based on overall content
    """
    if graph_data is None:
        graph_data = build_graph()

    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    if not nodes:
        return {
            "isolated": [], "unexpected": [], "gaps": [],
            "stats": {"total_nodes": 0, "total_edges": 0, "isolated_count": 0, "cross_category_connections": 0},
        }

    degree: dict[str, int] = {n["id"]: 0 for n in nodes}
    for e in edges:
        degree[e["source"]] = degree.get(e["source"], 0) + 1
        degree[e["target"]] = degree.get(e["target"], 0) + 1

    isolated = [
        {
            "id": n["id"], "title": n["label"],
            "category": n.get("category", "其他"), "degree": degree.get(n["id"], 0),
        }
        for n in nodes
        if n["type"] == "video" and degree.get(n["id"], 0) <= 1
    ]

    video_category = {n["id"]: n.get("category", "其他") for n in nodes if n["type"] == "video"}
    video_label = {n["id"]: n["label"] for n in nodes}
    unexpected = []
    for e in edges:
        src, tgt = e["source"], e["target"]
        if src in video_category and tgt in video_category and video_category[src] != video_category[tgt]:
            unexpected.append({
                "source": {"id": src, "title": video_label.get(src, src), "category": video_category[src]},
                "target": {"id": tgt, "title": video_label.get(tgt, tgt), "category": video_category[tgt]},
            })

    gaps = _identify_knowledge_gaps(nodes, isolated, unexpected)

    return {
        "isolated": isolated[:10],
        "unexpected": unexpected[:10],
        "gaps": gaps,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "isolated_count": len(isolated),
            "cross_category_connections": len(unexpected),
        },
    }


def _identify_knowledge_gaps(nodes: list[dict], isolated: list[dict], unexpected: list[dict]) -> list[dict]:
    video_nodes = [n for n in nodes if n["type"] == "video"]
    if not video_nodes:
        return []

    titles_summary = "\n".join(
        f"- {n['label']} ({n.get('category', '其他')})" for n in video_nodes[:30]
    )
    isolated_summary = "\n".join(f"- {i['title']}" for i in isolated[:5]) or "无"
    unexpected_summary = (
        "\n".join(
            f"- {u['source']['title']} ({u['source']['category']}) ←→ "
            f"{u['target']['title']} ({u['target']['category']})"
            for u in unexpected[:5]
        )
        or "无"
    )

    prompt = (
        "你是一个知识图谱分析专家。根据以下知识库内容，识别知识空白并生成研究建议。\n\n"
        f"知识库内容：\n{titles_summary}\n\n"
        f"孤立节点（关联较少）：\n{isolated_summary}\n\n"
        f"跨类别意外关联：\n{unexpected_summary}\n\n"
        "请输出严格 JSON 数组（最多5条，不要 markdown 代码块）：\n"
        '[{"gap_type":"isolated"或"unexpected"或"missing",'
        '"title":"空白主题名称","description":"为什么这是知识空白",'
        '"research_query":"用于进一步研究的具体问题","priority":"high"或"medium"或"low"}]'
    )

    try:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            max_tokens=800,
            messages=[
                {"role": "system", "content": "只输出JSON数组，不要任何解释。"},
                {"role": "user", "content": prompt},
            ],
        )
        raw = resp.choices[0].message.content or "[]"
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        return json.loads(match.group()) if match else []
    except Exception:
        return []
