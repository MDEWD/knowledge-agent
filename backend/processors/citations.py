"""Helpers for keeping retrieved candidates distinct from cited sources."""

import re


def select_cited_sources(answer: str, sources: list[dict]) -> list[dict]:
    """Return only sources referenced with an explicit ``[来源N]`` marker."""
    used = {int(value) for value in re.findall(r"\[来源\s*(\d+)\]", answer)}
    return [source for source in sources if source.get("index") in used]
