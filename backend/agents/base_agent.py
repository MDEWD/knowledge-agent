"""
BaseAgent: foundation for all sub-agents.
Each subclass defines its own system_prompt, tools, and tool executor.
"""
from __future__ import annotations

import json
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from openai import AsyncOpenAI

MAX_STEPS = 5


class BaseAgent:
    name: str = "BaseAgent"
    description: str = ""
    system_prompt: str = ""
    tools: list[dict] = []

    def __init__(self, client: "AsyncOpenAI", model: str):
        self.client = client
        self.model = model

    async def _execute_tool(self, tool_name: str, arguments: str) -> str:
        """Override in subclasses to implement tool logic."""
        return f"[{tool_name}] not implemented"

    async def run(self, task: str, context: str = "") -> str:
        """
        Execute the task using a ReAct loop (max MAX_STEPS iterations).
        Returns the final text result.
        """
        messages: list[dict] = [{"role": "system", "content": self.system_prompt}]
        if context:
            messages.append({"role": "user", "content": f"背景信息：\n{context}"})
        messages.append({"role": "user", "content": task})

        for _ in range(MAX_STEPS):
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools if self.tools else None,
                temperature=0.3,
            )
            choice = resp.choices[0]
            msg = choice.message

            if choice.finish_reason != "tool_calls" or not msg.tool_calls:
                return msg.content or ""

            # Append assistant turn
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })

            # Execute each tool call
            for tc in msg.tool_calls:
                result = await self._execute_tool(tc.function.name, tc.function.arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        # Exceeded max steps — ask for final answer without tools
        messages.append({
            "role": "user",
            "content": "请根据以上信息，直接给出最终答案。",
        })
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""
