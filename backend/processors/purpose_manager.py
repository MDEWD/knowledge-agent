from config import DATA_PATH

PURPOSE_FILE = DATA_PATH / "purpose.md"

_DEFAULT_TEMPLATE = """\
# 知识库定位

## 目标描述
（描述这个知识库的核心目标和关注方向，例如：专注于 AI 领域的前沿技术研究）

## 关键问题
- 我主要想探索哪些领域？
- 这个知识库要帮我回答什么核心问题？
- 我希望在哪些话题上建立深度理解？

## 研究范围
（列出主要的知识领域和话题范围，以及明确不包含的内容）
"""


def read_purpose() -> str:
    if not PURPOSE_FILE.exists():
        return ""
    return PURPOSE_FILE.read_text(encoding="utf-8")


def write_purpose(content: str) -> None:
    PURPOSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PURPOSE_FILE.write_text(content, encoding="utf-8")


def get_purpose_context() -> str:
    content = read_purpose().strip()
    if not content:
        return ""
    return f"【知识库定位与目标】\n{content}\n\n"


def get_default_template() -> str:
    return _DEFAULT_TEMPLATE
