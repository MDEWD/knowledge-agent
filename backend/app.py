import ssl
# 全局关闭 SSL 验证，解决自签名证书/代理证书问题
ssl._create_default_https_context = ssl._create_unverified_context

import asyncio
import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

from openai import AsyncOpenAI
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from extractors.generic import detect_platform, get_transcript as generic_transcript
from extractors.youtube import get_transcript as yt_transcript
from extractors.bilibili import get_transcript as bili_transcript
from processors.insights import extract_insights
from storage.obsidian import save_to_obsidian
from storage.vector_store import add_document, delete_document, search
from storage.video_db import add_video, delete_video, list_videos

# ── Task state ──────────────────────────────────────────────────────────────

task_queues: dict[str, asyncio.Queue] = {}

async def _push(task_id: str, event: dict) -> None:
    q = task_queues.get(task_id)
    if q:
        await q.put(event)


# ── Background pipeline ──────────────────────────────────────────────────────

async def _process_video(task_id: str, url: str, platform: str) -> None:
    try:
        await _push(task_id, {"step": "extracting", "progress": 10, "message": "正在提取字幕…"})

        loop = asyncio.get_event_loop()

        if platform == "youtube":
            result = await loop.run_in_executor(None, yt_transcript, url)
        elif platform == "bilibili":
            result = await loop.run_in_executor(None, bili_transcript, url)
        else:
            result = await loop.run_in_executor(None, generic_transcript, url)

        transcript = result["text"]
        metadata = result["metadata"]
        metadata["id"] = hashlib.md5(url.encode()).hexdigest()[:12]

        await _push(task_id, {"step": "processing", "progress": 45, "message": "DeepSeek 正在提炼核心观点…"})

        insights = await loop.run_in_executor(None, extract_insights, transcript, metadata)

        await _push(task_id, {"step": "saving", "progress": 80, "message": "写入 Obsidian 和向量库…"})

        obsidian_path = await loop.run_in_executor(None, save_to_obsidian, insights, metadata, transcript)
        await loop.run_in_executor(None, add_document, insights, metadata)

        # Extract summary and tags from insights for quick display
        summary = ""
        tags: list[str] = []
        for line in insights.splitlines():
            if line.startswith("## 核心摘要"):
                continue
            if line.startswith("## "):
                if summary:
                    break
            elif summary == "" and line.strip():
                summary = line.strip()
            if "#" in line and not line.startswith("#"):
                tags = [t.lstrip("#") for t in line.split() if t.startswith("#")]

        video_record = {
            **metadata,
            "insights": insights,
            "summary": summary,
            "tags": tags,
            "obsidian_path": str(obsidian_path),
            "created_at": datetime.now().isoformat(),
        }
        await loop.run_in_executor(None, add_video, video_record)

        await _push(task_id, {
            "step": "done",
            "progress": 100,
            "message": "完成！",
            "video": {k: v for k, v in video_record.items() if k != "insights"},
        })

    except Exception as exc:
        await _push(task_id, {"step": "error", "progress": 0, "message": str(exc)})
    finally:
        # Keep queue alive briefly for late SSE connects, then clean up
        await asyncio.sleep(30)
        task_queues.pop(task_id, None)


# ── FastAPI ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="Knowledge Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ──────────────────────────────────────────────────────────────────

class ProcessRequest(BaseModel):
    url: str
    platform: str = "generic"

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]

    def as_dicts(self) -> list[dict]:
        return [m.model_dump() for m in self.messages]


# ── Video processing endpoints ───────────────────────────────────────────────

@app.post("/api/process-video")
async def process_video(req: ProcessRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    task_queues[task_id] = asyncio.Queue()
    background_tasks.add_task(_process_video, task_id, req.url, req.platform)
    return {"task_id": task_id}


@app.get("/api/status/{task_id}")
async def stream_status(task_id: str):
    if task_id not in task_queues:
        raise HTTPException(status_code=404, detail="Task not found")

    async def generate() -> AsyncGenerator[str, None]:
        q = task_queues[task_id]
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=60)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("step") in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                yield "data: {\"step\":\"ping\"}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Video library endpoints ──────────────────────────────────────────────────

@app.get("/api/videos")
async def get_videos():
    videos = list_videos()
    return [
        {k: v for k, v in video.items() if k != "insights"}
        for video in videos
    ]


@app.delete("/api/videos/{video_id}")
async def remove_video(video_id: str):
    videos = list_videos()
    video = next((v for v in videos if v.get("id") == video_id), None)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    delete_document(video["url"])
    deleted = delete_video(video_id)
    return {"deleted": deleted}


# ── Chat endpoint ─────────────────────────────────────────────────────────────

_CHAT_SYSTEM = """\
你是用户的个人知识助手。用户学习了一些视频，这些视频的知识笔记存储在知识库中。
当用户提问时，先用 search_knowledge_base 工具搜索相关内容，再基于检索结果回答。
回答用中文，引用来源时请注明视频标题和链接。如果知识库中没有相关内容，如实告知。
"""

# OpenAI / DeepSeek function-calling format
_TOOLS = [{
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": "搜索个人视频知识库，返回相关笔记片段",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词或问题"},
            },
            "required": ["query"],
        },
    },
}]


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    async_client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    async def generate() -> AsyncGenerator[str, None]:
        messages: list[dict] = [
            {"role": "system", "content": _CHAT_SYSTEM},
            *req.as_dicts(),
        ]
        loop = asyncio.get_event_loop()

        for _ in range(5):  # max 5 tool-use iterations
            # Accumulate streaming tool-call deltas
            tool_calls_acc: dict[int, dict] = {}
            finish_reason: str | None = None

            stream = await async_client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                max_tokens=2048,
                messages=messages,
                tools=_TOOLS,
                stream=True,
            )

            async for chunk in stream:
                choice = chunk.choices[0]
                delta = choice.delta

                # Stream text tokens immediately
                if delta.content:
                    yield f"data: {json.dumps({'type': 'text', 'content': delta.content}, ensure_ascii=False)}\n\n"

                # Accumulate tool-call argument deltas
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        i = tc_delta.index
                        if i not in tool_calls_acc:
                            tool_calls_acc[i] = {"id": "", "name": "", "arguments": ""}
                        if tc_delta.id:
                            tool_calls_acc[i]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_acc[i]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_acc[i]["arguments"] += tc_delta.function.arguments

                if choice.finish_reason:
                    finish_reason = choice.finish_reason

            if finish_reason != "tool_calls" or not tool_calls_acc:
                break

            # Build assistant message with tool_calls array (OpenAI format)
            tool_call_list = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in (tool_calls_acc[k] for k in sorted(tool_calls_acc))
            ]
            messages.append({"role": "assistant", "content": None, "tool_calls": tool_call_list})

            # Execute tools, stream indicator, append tool results
            for tc in tool_call_list:
                if tc["function"]["name"] == "search_knowledge_base":
                    try:
                        args = json.loads(tc["function"]["arguments"])
                        query = args.get("query", "")
                    except json.JSONDecodeError:
                        query = ""

                    yield f"data: {json.dumps({'type': 'searching', 'query': query}, ensure_ascii=False)}\n\n"
                    results = await loop.run_in_executor(None, search, query)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(results, ensure_ascii=False),
                    })

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
