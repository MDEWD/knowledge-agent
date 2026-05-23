"""Dream Cycle: autonomous background maintenance.

Runs nightly to keep the knowledge base healthy:
1. Recompute significance scores for all videos
2. Scan Obsidian notes for broken wikilinks
3. Collect contradictions flagged during two-step ingestion
4. Identify isolated nodes in the knowledge graph
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from config import DATA_PATH, OBSIDIAN_VAULT_PATH

_REPORT_FILE = DATA_PATH / "dream_cycle_report.json"


def _update_significance_scores() -> dict:
    from processors.significance import compute_all_significance
    from storage.video_db import batch_update_significance

    scores = compute_all_significance()
    if scores:
        batch_update_significance(scores)
    top5 = sorted(scores.items(), key=lambda x: -x[1])[:5]
    return {"updated": len(scores), "top_5": [{"id": k, "score": v} for k, v in top5]}


def _scan_broken_wikilinks() -> dict:
    if not OBSIDIAN_VAULT_PATH.exists():
        return {"count": 0, "items": []}

    existing: set[str] = set()
    for f in OBSIDIAN_VAULT_PATH.rglob("*.md"):
        stem = f.stem
        existing.add(stem)
        if re.match(r'^\d{4}-\d{2}-\d{2} ', stem):
            existing.add(stem[11:])  # strip date prefix variant

    broken: list[dict] = []
    for f in OBSIDIAN_VAULT_PATH.rglob("*.md"):
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for link in re.findall(r'\[\[([^\]|#\n]+?)(?:\|[^\]]*)?\]\]', content):
            link = link.strip()
            if link and link not in existing:
                broken.append({
                    "source": str(f.relative_to(OBSIDIAN_VAULT_PATH)),
                    "broken_link": link,
                })

    return {"count": len(broken), "items": broken[:20]}


def _collect_contradictions() -> dict:
    from storage.video_db import list_videos

    contradiction_keywords = ["矛盾", "相反", "冲突", "不同意", "contradict", "disagree"]
    found: list[dict] = []

    for v in list_videos():
        insights = v.get("insights", "")
        if not insights:
            continue
        m = re.search(r'##\s*知识关联(.*?)(?=##|\Z)', insights, re.DOTALL)
        if m:
            section = m.group(1)
            if any(kw in section for kw in contradiction_keywords):
                found.append({
                    "video_id": v.get("id"),
                    "title": v.get("title", ""),
                    "note": section.strip()[:300],
                })

    return {"count": len(found), "items": found[:10]}


def _find_isolated_nodes() -> dict:
    from processors.knowledge_graph import analyze_gaps

    isolated = analyze_gaps().get("isolated", [])
    return {"count": len(isolated), "items": isolated[:10]}


def run_dream_cycle() -> dict:
    """Orchestrate all maintenance tasks and write a consolidated report."""
    started_at = datetime.now().isoformat()
    print(f"[DreamCycle] Start {started_at}")

    report: dict = {"started_at": started_at, "tasks": {}}

    for task_name, task_fn in [
        ("significance", _update_significance_scores),
        ("broken_wikilinks", _scan_broken_wikilinks),
        ("contradictions", _collect_contradictions),
        ("isolated_nodes", _find_isolated_nodes),
    ]:
        try:
            report["tasks"][task_name] = task_fn()
            print(f"[DreamCycle] {task_name}: OK")
        except Exception as e:
            report["tasks"][task_name] = {"error": str(e)}
            print(f"[DreamCycle] {task_name}: ERROR — {e}")

    report["completed_at"] = datetime.now().isoformat()
    _REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DreamCycle] Done {report['completed_at']}")
    return report


def load_last_report() -> dict:
    if not _REPORT_FILE.exists():
        return {}
    try:
        return json.loads(_REPORT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
