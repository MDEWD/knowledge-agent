"""
SkillExtractor: turn a successful agent transcript into reusable Skill records.

Voyager's insight is that skills should be *automatically* extracted from
verified runs rather than hand-authored.  This extractor uses an LLM to
analyse a (task, transcript) pair and produces zero or more Skill objects.

The LLM is asked to:
  1. Decide whether the run contains a generalisable pattern worth saving.
  2. If yes, write a structured Skill JSON with name / description / procedure.

A strict JSON schema is enforced to prevent hallucination drift.
"""
from __future__ import annotations

import json
import logging
import uuid

from openai import AsyncOpenAI

from .skill_store import Skill

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are a skill extraction engine for an AI agent system.

Your job: analyse a completed agent run and decide whether it contains a
reusable, generalisable pattern that should be saved as a "skill".

A skill is worth extracting when:
- The agent solved a non-trivial problem in a repeatable way.
- The same technique would be useful for similar future tasks.
- The solution is not obvious from the task description alone.

Return ONLY valid JSON in this exact format (no markdown fences):
{
  "extract": true | false,
  "skills": [
    {
      "name": "<short title, ≤ 60 chars>",
      "description": "<one paragraph: what the skill does and when to use it>",
      "procedure": "<numbered steps an agent can follow>",
      "tags": ["tag1", "tag2"]
    }
  ]
}

If extract is false, skills must be an empty array.
Produce at most 2 skills per run.  Quality over quantity.
"""


class SkillExtractor:
    """
    Extracts reusable skills from a successful agent run.

    Parameters
    ----------
    client  : AsyncOpenAI-compatible client.
    model   : Model to use for extraction (should be fast/cheap).
    """

    def __init__(self, client: AsyncOpenAI, model: str = "deepseek-chat") -> None:
        self._client = client
        self._model = model

    async def extract(self, task: str, transcript: str) -> list[Skill]:
        """
        Analyse (task, transcript) and return a list of extracted Skills.

        Returns an empty list if the run contains nothing worth saving or if
        the LLM response cannot be parsed.

        Parameters
        ----------
        task        : The original top-level task string.
        transcript  : Condensed agent run log — tool calls, observations,
                      final answer.  Truncated to 4000 chars if longer.
        """
        transcript = transcript[:4000]
        user_content = (
            f"TASK:\n{task}\n\n"
            f"TRANSCRIPT:\n{transcript}"
        )

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                temperature=0.0,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            )
        except Exception as exc:
            logger.warning("[skill_extractor] LLM call failed: %s", exc)
            return []

        raw = response.choices[0].message.content or ""
        return self._parse(raw, task)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse(self, raw: str, source_task: str) -> list[Skill]:
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            logger.warning("[skill_extractor] non-JSON response: %s", raw[:200])
            return []

        if not data.get("extract"):
            return []

        skills: list[Skill] = []
        for item in data.get("skills", []):
            try:
                skill = Skill(
                    skill_id=str(uuid.uuid4()),
                    name=str(item["name"])[:60],
                    description=str(item["description"]),
                    procedure=str(item["procedure"]),
                    tags=[str(t) for t in item.get("tags", [])],
                    source_task=source_task,
                )
                skills.append(skill)
            except (KeyError, TypeError) as exc:
                logger.warning("[skill_extractor] malformed skill item: %s", exc)

        logger.info("[skill_extractor] extracted %d skill(s)", len(skills))
        return skills
