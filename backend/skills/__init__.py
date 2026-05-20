"""
Skill: a reusable, verified solution extracted from a successful agent run.

Voyager-style skill library: the agent accumulates skills over time and
retrieves the most relevant ones at the start of each new task.  This
gives the agent "long-term procedural memory" beyond what fits in the
context window.

Architecture
  - Skill          immutable value object (JSON-serialisable)
  - SkillStore     CRUD + semantic search over all stored skills
  - SkillExtractor prompt-based extractor that turns a run transcript
                   into zero or more Skill records

Usage:
    store = SkillStore("data/skills")

    # After a successful run, extract and save skills
    extractor = SkillExtractor(openai_client, model="deepseek-chat")
    skills = await extractor.extract(task, transcript)
    for skill in skills:
        store.save(skill)

    # At the start of the next run, retrieve relevant skills
    relevant = store.search(new_task, top_k=3)
    context_block = "\\n\\n".join(s.to_prompt_block() for s in relevant)
"""
from .skill_store import Skill, SkillStore
from .skill_extractor import SkillExtractor

__all__ = ["Skill", "SkillStore", "SkillExtractor"]
