"""Per-video significance scoring.

Score = weighted blend of:
  - graph connectivity  (40%): edge count in knowledge graph
  - SM-2 recall ease    (30%): average ease_factor from recall cards
  - review count        (20%): total repetitions across all cards
  - tag richness        (10%): number of tags on the video
"""
from __future__ import annotations


def compute_significance(video: dict, graph_edges: list[dict] | None = None) -> float:
    """Return a 0.0–1.0 significance score for a single video."""
    video_id = video.get("id", "")

    # 1. Graph connectivity (40%)
    graph_degree = 0
    if graph_edges:
        node_id = f"v_{video_id}"
        graph_degree = sum(
            1 for e in graph_edges
            if e.get("source") == node_id or e.get("target") == node_id
        )

    # 2. SM-2 recall performance (30%)
    avg_ease = 0.0
    total_reps = 0
    try:
        from storage.recall_db import list_cards
        cards = list_cards(video_id)
        if cards:
            avg_ease = sum(c.get("ease_factor", 2.5) for c in cards) / len(cards)
            total_reps = sum(c.get("repetitions", 0) for c in cards)
    except Exception:
        pass

    # 3. Tag richness (10%)
    tag_count = len(video.get("tags") or [])

    # Normalize each component to [0, 1]
    connectivity = min(graph_degree / 10.0, 1.0)
    recall_ease = max(min((avg_ease - 1.3) / 1.2, 1.0), 0.0) if avg_ease > 0 else 0.0
    reviews = min(total_reps / 20.0, 1.0)
    tags = min(tag_count / 8.0, 1.0)

    return round(0.4 * connectivity + 0.3 * recall_ease + 0.2 * reviews + 0.1 * tags, 4)


def compute_all_significance() -> dict[str, float]:
    """Compute significance scores for all videos. Returns {video_id: score}."""
    from storage.video_db import list_videos
    from processors.knowledge_graph import build_graph

    videos = list_videos()
    if not videos:
        return {}

    edges = build_graph().get("edges", [])
    return {v["id"]: compute_significance(v, edges) for v in videos}


def get_significance_map() -> dict[str, float]:
    """Load cached significance scores from videos.json (fast, no LLM calls)."""
    try:
        from storage.video_db import list_videos
        return {v["id"]: v.get("significance_score", 0.0) for v in list_videos()}
    except Exception:
        return {}
