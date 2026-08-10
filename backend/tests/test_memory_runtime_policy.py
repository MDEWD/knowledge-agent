from datetime import datetime

from memory.runtime import (
    MemoryCandidate,
    MemoryRuntime,
    _scope_relation,
    _similarity,
)


def test_scope_specialization_is_not_a_direct_conflict():
    assert _scope_relation({}, {"task_type": "deep_research"}) == "candidate_more_specific"
    assert _scope_relation(
        {"task_type": "general_chat"},
        {"task_type": "deep_research"},
    ) == "disjoint"
    assert _scope_relation(
        {"task_type": "deep_research"},
        {"task_type": "deep_research"},
    ) == "same"


def test_explicit_user_correction_supersedes_same_scope():
    runtime = MemoryRuntime("test-user")
    existing = {
        "explicitness": 1.0,
        "confidence": 0.95,
        "source_type": "explicit_user",
        "updated_at": datetime(2026, 1, 1),
    }
    candidate = MemoryCandidate(
        category="profile",
        memory_type="preference",
        key="response_length",
        value="detailed",
        explicitness=1.0,
        confidence=0.98,
        importance=0.9,
        source_type="user_correction",
    )
    assert runtime._should_supersede(existing, candidate, datetime(2026, 8, 4)) is True


def test_inference_does_not_override_explicit_fact():
    runtime = MemoryRuntime("test-user")
    existing = {
        "explicitness": 1.0,
        "confidence": 0.95,
        "source_type": "explicit_user",
        "updated_at": datetime(2026, 8, 1),
    }
    candidate = MemoryCandidate(
        category="profile",
        memory_type="preference",
        key="response_length",
        value="detailed",
        explicitness=0.5,
        confidence=0.7,
        importance=0.6,
        source_type="chat_inference",
    )
    assert runtime._should_supersede(existing, candidate, datetime(2026, 8, 4)) is False


def test_chinese_task_similarity_uses_character_ngrams():
    assert _similarity("深度研究报告", "用户喜欢详细的深度研究") > 0


def test_working_memory_is_bounded_and_marks_scope():
    runtime = MemoryRuntime("test-user")
    rendered = runtime.format_working_memory([
        {
            "memory_type": "preference",
            "key": "response_length",
            "scope": {"task_type": "deep_research"},
            "confidence": 0.98,
            "content": "深度研究需要详细回答",
        }
    ], max_chars=300)
    assert "Working Memory" in rendered
    assert "task_type=deep_research" in rendered
    assert "深度研究需要详细回答" in rendered
