"""Progressively load project-owned SKILL.md instructions."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_CN_FUND_PATTERN = re.compile(
    r"(?:公募基金|基金经理|基金净值|基金持仓|基金规模|ETF|etf|回撤|夏普|索提诺|"
    r"基金代码|跟踪指数|[015]\d{5}(?:\.(?:OF|SH|SZ))?)"
)


@dataclass(frozen=True, slots=True)
class FileSkill:
    name: str
    description: str
    directory: Path
    instructions: str

    def prompt_block(self) -> str:
        return f"<agent_skill name=\"{self.name}\">\n{self.instructions}\n</agent_skill>"


class FileSkillRegistry:
    """Discovers Skills but only routes explicitly trusted project Skills."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else Path(__file__).resolve().parent
        self._skills = self._load()

    def get(self, name: str) -> FileSkill | None:
        return self._skills.get(name)

    def match(self, task: str) -> list[FileSkill]:
        names: list[str] = []
        if _CN_FUND_PATTERN.search(task or ""):
            names.append("cn-fund-research")
        return [self._skills[name] for name in names if name in self._skills]

    def prompt_for(self, task: str) -> str:
        matched = self.match(task)
        if not matched:
            return ""
        return "\n\n".join(skill.prompt_block() for skill in matched)

    def list_all(self) -> list[dict[str, str]]:
        return [
            {"name": item.name, "description": item.description, "path": str(item.directory)}
            for item in self._skills.values()
        ]

    def _load(self) -> dict[str, FileSkill]:
        result: dict[str, FileSkill] = {}
        if not self.root.exists():
            return result
        for path in self.root.glob("*/SKILL.md"):
            raw = path.read_text(encoding="utf-8")
            metadata, body = _split_frontmatter(raw)
            name = metadata.get("name", path.parent.name).strip()
            description = metadata.get("description", "").strip()
            if name:
                result[name] = FileSkill(name, description, path.parent, body.strip())
        return result


def _split_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---"):
        return {}, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw
    metadata: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata, parts[2]


def is_cn_fund_research(task: str) -> bool:
    return bool(_CN_FUND_PATTERN.search(task or ""))


__all__ = ["FileSkill", "FileSkillRegistry", "is_cn_fund_research"]
