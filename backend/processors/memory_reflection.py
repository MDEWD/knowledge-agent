"""Reflection Cycle: consolidate multiple Memory Observations into insights."""

from __future__ import annotations

import json
import uuid

from openai import OpenAI

from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    MEMORY_REFLECTION_THRESHOLD,
)
from memory.runtime import MemoryCandidate, MemoryRuntime


def run_memory_reflection(force: bool = False) -> dict:
    runtime = MemoryRuntime()
    pending = runtime.pending_reflection_count()
    if pending == 0 or (not force and pending < MEMORY_REFLECTION_THRESHOLD):
        return {"status": "skipped", "pending": pending, "threshold": MEMORY_REFLECTION_THRESHOLD}

    observations = runtime.get_unreflected_observations(
        limit=max(MEMORY_REFLECTION_THRESHOLD, 50)
    )
    observation_text = ""
    for observation in observations:
        block = f"\n[Observation {observation['id']}]\n{observation['content'][:2500]}\n"
        if len(observation_text) + len(block) > 40_000:
            break
        observation_text += block
    selected_ids = [
        observation["id"]
        for observation in observations
        if f"[Observation {observation['id']}]" in observation_text
    ]

    facts = runtime.list_active_facts(limit=80)
    fact_context = json.dumps(
        [
            {
                "type": fact["memory_type"],
                "key": fact["memory_key"],
                "content": fact["content"],
                "scope": fact["scope"],
                "confidence": fact["confidence"],
            }
            for fact in facts
        ],
        ensure_ascii=False,
    )[:20_000]

    prompt = f"""Run a production Agent Memory Reflection Cycle.

Derive only stable insights supported by at least two Memory Observations. Do
not copy raw conversations, secrets, one-off task details, assistant claims or
web facts. Prefer reusable user preferences, stable goals and learned working
procedures. Preserve task-specific scope. Do not overwrite an existing fact in
the output unless the observations provide clear evidence of change.

Return JSON only:
{{
  "memories": [
    {{
      "category": "profile|semantic|procedural",
      "type": "preference|learning_goal|key_insight|procedure|semantic",
      "key": "stable_snake_case_predicate",
      "value": "structured value",
      "content": "short consolidated insight",
      "scope": {{}},
      "confidence": 0.0,
      "importance": 0.0,
      "explicitness": 0.0,
      "ttl_days": 180
    }}
  ]
}}

Current active Memory Facts:
{fact_context}

Unreflected Memory Observations:
{observation_text}
"""
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        max_tokens=1600,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Consolidate Agent memory. Return JSON only."},
            {"role": "user", "content": prompt},
        ],
    )
    try:
        payload = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return {"status": "invalid_json", "pending": pending}

    reflection_id = str(uuid.uuid4())
    candidates = []
    for item in (payload.get("memories") or [])[:15]:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        item["source_type"] = "reflection"
        item["source_id"] = reflection_id
        item["explicitness"] = min(0.7, float(item.get("explicitness") or 0.5))
        try:
            candidates.append(MemoryCandidate.from_dict(item))
        except (TypeError, ValueError):
            continue

    result = runtime.remember(candidates)
    runtime.link_observations(result["fact_ids"], selected_ids)
    runtime.mark_reflected(selected_ids)
    return {
        "status": "completed",
        "observations": len(selected_ids),
        "memories": len(result["fact_ids"]),
        "conflicts": result["conflicts"],
    }
