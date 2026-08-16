from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from agents.deep_research.tool_runtime import ToolDefinition, ToolRuntime


def _call(call_id: str, name: str, arguments: str):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _message(*calls, content: str = "", reasoning: str | None = None):
    return SimpleNamespace(
        content=content,
        reasoning_content=reasoning,
        tool_calls=list(calls),
    )


@pytest.mark.asyncio
async def test_execute_turn_returns_one_contiguous_response_per_tool_call():
    async def add(left: int, right: int) -> dict:
        await asyncio.sleep(0)
        return {"total": left + right}

    def greet(name: str) -> str:
        return f"hello {name}"

    runtime = ToolRuntime({"add": add, "greet": greet})
    turn = await runtime.execute_turn(
        _message(
            _call("call-1", "add", '{"left": 2, "right": 3}'),
            _call("call-2", "greet", '{"name": "Ada"}'),
        )
    )

    assert [message["role"] for message in turn.messages] == [
        "assistant",
        "tool",
        "tool",
    ]
    assert [message["tool_call_id"] for message in turn.messages[1:]] == [
        "call-1",
        "call-2",
    ]
    assert json.loads(turn.messages[1]["content"]) == {"total": 5}
    assert turn.messages[2]["content"] == "hello Ada"
    assert turn.usage.tool_calls == 2


@pytest.mark.asyncio
async def test_execute_response_returns_atomic_function_call_outputs():
    async def lookup(query: str) -> dict:
        return {"query": query, "sources": 3}

    runtime = ToolRuntime({"lookup": lookup})
    response = SimpleNamespace(
        output=[
            {
                "type": "function_call",
                "call_id": "response-call-1",
                "name": "lookup",
                "arguments": '{"query":"semiconductors"}',
            }
        ],
        output_text="",
        usage=SimpleNamespace(input_tokens=23, output_tokens=7),
    )

    turn = await runtime.execute_response(response)

    assert [item["type"] for item in turn.input_items] == [
        "function_call",
        "function_call_output",
    ]
    assert turn.input_items[1]["call_id"] == "response-call-1"
    assert json.loads(turn.input_items[1]["output"]) == {
        "query": "semiconductors",
        "sources": 3,
    }
    assert [message["role"] for message in turn.messages] == ["assistant", "tool"]
    assert turn.usage.as_dict() == {
        "input_tokens": 23,
        "output_tokens": 7,
        "tool_calls": 1,
    }


@pytest.mark.asyncio
async def test_unknown_tool_is_a_tool_message_not_an_exception():
    runtime = ToolRuntime({})

    turn = await runtime.execute_turn(
        _message(_call("missing-1", "does_not_exist", "{}"))
    )

    error = json.loads(turn.messages[1]["content"])
    assert error["ok"] is False
    assert error["error"]["type"] == "unknown_tool"
    assert turn.results[0].status == "error"
    assert turn.usage.tool_calls == 1


@pytest.mark.asyncio
async def test_invalid_arguments_and_handler_errors_both_close_the_protocol_block():
    def explode(value: int) -> None:
        raise RuntimeError(f"bad value: {value}")

    runtime = ToolRuntime(
        {
            "explode": ToolDefinition(
                handler=explode,
                parameters={
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            )
        }
    )

    turn = await runtime.execute_turn(
        _message(
            _call("bad-json", "explode", "not-json"),
            _call("bad-schema", "explode", '{"value": "one"}'),
            _call("raises", "explode", '{"value": 1}'),
        )
    )

    assert len(turn.messages) == 4
    assert [result.status for result in turn.results] == ["error", "error", "error"]
    error_types = [
        json.loads(message["content"])["error"]["type"]
        for message in turn.messages[1:]
    ]
    assert error_types == ["invalid_arguments", "invalid_arguments", "tool_error"]


@pytest.mark.asyncio
async def test_per_tool_timeout_returns_tool_message_and_emits_events():
    async def slow() -> str:
        await asyncio.sleep(0.1)
        return "late"

    events: list[dict] = []

    async def collect(event: dict) -> None:
        events.append(event)

    runtime = ToolRuntime(
        {"slow": ToolDefinition(slow, timeout_seconds=0.01)},
        event_sink=collect,
    )
    turn = await runtime.execute_turn(_message(_call("slow-1", "slow", "{}")))

    error = json.loads(turn.messages[1]["content"])
    assert error["error"]["type"] == "timeout"
    assert [event["type"] for event in events] == ["tool_start", "tool_finish"]
    assert events[-1]["status"] == "timeout"


@pytest.mark.asyncio
async def test_reasoning_content_and_llm_usage_are_preserved():
    runtime = ToolRuntime({})

    turn = await runtime.execute_turn(
        _message(content="plan", reasoning="private chain"),
        usage=SimpleNamespace(prompt_tokens=17, completion_tokens=9),
    )

    assert turn.messages == (
        {
            "role": "assistant",
            "content": "plan",
            "reasoning_content": "private chain",
        },
    )
    assert turn.usage.as_dict() == {
        "input_tokens": 17,
        "output_tokens": 9,
        "tool_calls": 0,
    }


def test_assemble_turn_closes_custom_scheduled_tool_block():
    runtime = ToolRuntime()
    turn = runtime.assemble_turn(
        _message(
            _call("parallel-1", "ConductResearch", '{"topic":"a"}'),
            _call("parallel-2", "ConductResearch", '{"topic":"b"}'),
        ),
        {"parallel-1": "note a"},
    )

    assert [message["role"] for message in turn.messages] == ["assistant", "tool", "tool"]
    assert turn.messages[1]["content"] == "note a"
    assert json.loads(turn.messages[2]["content"])["error"]["type"] == "unhandled_tool_call"
