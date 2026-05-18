import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import asyncio
import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from openai import AsyncOpenAI
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from extractors.generic import get_transcript as generic_transcript
from extractors.youtube import get_transcript as yt_transcript
from extractors.bilibili import get_transcript as bili_transcript
from processors.insights import extract_insights, parse_category, is_mainly_chinese, translate_to_chinese
from storage.obsidian import save_to_obsidian, update_obsidian_note
from storage.vector_store import add_document, delete_document, find_related, search
from storage.video_db import add_video, delete_video, get_video, list_videos, update_video_note


# ── Scheduler ─────────────────────────────────────────────────────────────────

_scheduler = AsyncIOScheduler()


def _run_weekly_review() -> None:
    from processors.review import generate_weekly_review
    generate_weekly_review(days=7)


def _sync_bm25_from_chroma() -> None:
    """
    One-time migration: populate BM25 corpus from existing ChromaDB data.
    Runs at startup only if BM25 corpus is empty (i.e. first launch after upgrade).
    """
    from storage import bm25_store
    from storage.vector_store import _get_collection
    if bm25_store.corpus_size() > 0:
        return
    try:
        col = _get_collection()
        results = col.get(include=["documents", "metadatas"])
        if not results["ids"]:
            return
        items = [
            {"id": doc_id, "text": doc, "metadata": meta}
            for doc_id, doc, meta in zip(
                results["ids"], results["documents"], results["metadatas"]
            )
        ]
        bm25_store.add_documents(items)
        print(f"[BM25] Synced {len(items)} chunks from ChromaDB")
    except Exception as e:
        print(f"[BM25] Sync error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _scheduler.add_job(
        _run_weekly_review,
        CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="weekly_review",
        replace_existing=True,
    )
    _scheduler.start()
    # Populate BM25 from Chroma on first startup after upgrade
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_bm25_from_chroma)
    yield
    _scheduler.shutdown()


# ── App & middleware ───────────────────────────────────────────────────────────

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

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


class NoteUpdateRequest(BaseModel):
    insights: str


class ReviewChatRequest(BaseModel):
    review_content: str
    messages: list[ChatMessage]

    def as_dicts(self) -> list[dict]:
        return [m.model_dump() for m in self.messages]


class ArticleRequest(BaseModel):
    topic: str


class ReviewRequest(BaseModel):
    days: int = 7


# ── Task state ────────────────────────────────────────────────────────────────

task_queues: dict[str, asyncio.Queue] = {}


async def _push(task_id: str, event: dict) -> None:
    q = task_queues.get(task_id)
    if q:
        await q.put(event)


# ── Background pipeline ───────────────────────────────────────────────────────

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

        original_transcript = ""
        if not is_mainly_chinese(transcript):
            await _push(task_id, {"step": "processing", "progress": 30, "message": "检测到英文内容，正在翻译字幕…"})
            original_transcript = transcript
            transcript = await loop.run_in_executor(None, translate_to_chinese, transcript)

        await _push(task_id, {"step": "processing", "progress": 45, "message": "DeepSeek 正在提炼核心观点…"})

        insights = await loop.run_in_executor(None, extract_insights, transcript, metadata)

        await _push(task_id, {"step": "saving", "progress": 80, "message": "写入 Obsidian 和向量库…"})

        obsidian_path = await loop.run_in_executor(
            None, save_to_obsidian, insights, metadata, transcript, original_transcript
        )
        await loop.run_in_executor(None, add_document, insights, metadata)

        related = await loop.run_in_executor(
            None, find_related, metadata["id"], metadata.get("title", "")
        )

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
            "transcript": transcript,
            "original_transcript": original_transcript,
            "category": parse_category(insights),
            "related_ids": [r["id"] for r in related],
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
            "video": {k: v for k, v in video_record.items() if k not in ("insights", "transcript", "original_transcript")},
        })

    except Exception as exc:
        await _push(task_id, {"step": "error", "progress": 0, "message": str(exc)})
    finally:
        await asyncio.sleep(30)
        task_queues.pop(task_id, None)


def _reindex_note(video: dict, new_insights: str) -> None:
    delete_document(video["url"])
    add_document(new_insights, video)


# ── Chat: tools & system prompt ───────────────────────────────────────────────

_CHAT_SYSTEM = """\
你是用户的个人知识助手，拥有多种工具来帮助用户探索和利用他们的视频知识库。

工具使用策略：
- 先用 search_knowledge_base 搜索相关内容再回答
- 用户问"有哪些视频"时，用 list_videos_in_kb 列出
- 用户问某分类的总结时，用 summarize_category
- 用户让你对比几个视频时，先用 list_videos_in_kb 找到 ID，再用 compare_videos
- 知识库中没有相关内容时，用 search_youtube_videos 搜索推荐
- 用户要求生成综合文章时，用 generate_synthesis_article

回答用中文，引用来源时注明视频标题。
"""

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "语义搜索个人视频知识库，返回相关笔记片段",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "搜索关键词或问题"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_video_note",
            "description": "获取某个视频的完整笔记内容",
            "parameters": {
                "type": "object",
                "properties": {"video_id": {"type": "string", "description": "视频ID"}},
                "required": ["video_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_videos_in_kb",
            "description": "列出知识库中的所有视频，可按分类筛选",
            "parameters": {
                "type": "object",
                "properties": {"category": {"type": "string", "description": "可选，按分类名称筛选"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_category",
            "description": "对某个分类下的所有视频知识进行综合总结",
            "parameters": {
                "type": "object",
                "properties": {"category": {"type": "string", "description": "分类名称"}},
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_videos",
            "description": "对比多个视频的核心观点，找出共识和分歧",
            "parameters": {
                "type": "object",
                "properties": {
                    "video_ids": {"type": "array", "items": {"type": "string"}, "description": "视频ID列表"},
                    "topic": {"type": "string", "description": "对比的主题或角度（可选）"},
                },
                "required": ["video_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_youtube_videos",
            "description": "当知识库中没有相关内容时，在YouTube上搜索推荐视频",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "搜索词"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_synthesis_article",
            "description": "基于知识库中的相关内容，生成一篇系统性综合文章并保存到Obsidian",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string", "description": "文章主题"}},
                "required": ["topic"],
            },
        },
    },
]

_TOOL_LABELS: dict[str, str] = {
    "search_knowledge_base": "搜索知识库",
    "get_video_note": "读取笔记",
    "list_videos_in_kb": "列出视频",
    "summarize_category": "汇总分类",
    "compare_videos": "对比视频",
    "search_youtube_videos": "搜索 YouTube",
    "generate_synthesis_article": "生成综合文章",
}

_COMPRESS_AT = 14


async def _compress_history(messages: list[dict], client: AsyncOpenAI) -> list[dict]:
    non_system = [m for m in messages if m["role"] != "system"]
    if len(non_system) <= _COMPRESS_AT:
        return messages
    system_msgs = [m for m in messages if m["role"] == "system"]
    recent = non_system[-6:]
    old = non_system[:-6]
    text = "\n".join(
        f"[{m['role']}]: {m.get('content') or ''}"
        for m in old if isinstance(m.get("content"), str)
    )
    resp = await client.chat.completions.create(
        model=DEEPSEEK_MODEL, max_tokens=300,
        messages=[
            {"role": "system", "content": "请用中文简洁总结以下对话的关键信息，100字以内。"},
            {"role": "user", "content": text},
        ],
    )
    summary = resp.choices[0].message.content or "（早期对话已压缩）"
    return system_msgs + [{"role": "system", "content": f"【对话历史摘要】{summary}"}] + recent


async def _execute_tool(name: str, arguments: str, loop) -> tuple[str, list | None]:
    try:
        args = json.loads(arguments)
    except Exception:
        args = {}

    if name == "search_knowledge_base":
        query = args.get("query", "")
        results = await loop.run_in_executor(None, search, query)
        if not results:
            return "知识库中没有相关内容。", None
        # Warn the LLM when results may not be genuinely relevant
        from storage.vector_store import is_topic_covered
        covered = await loop.run_in_executor(None, is_topic_covered, query, 1, 1.0)
        if not covered:
            return (
                "【注意：知识库中暂无与该主题高度相关的内容，以下为最近似的结果，相关性可能较低】\n\n"
                + json.dumps(results, ensure_ascii=False)
            ), None
        return json.dumps(results, ensure_ascii=False), None

    if name == "get_video_note":
        v = get_video(args.get("video_id", ""))
        if not v:
            return "未找到该视频", None
        return f"**{v['title']}**\n\n{v.get('insights', '暂无笔记')}", None

    if name == "list_videos_in_kb":
        category = args.get("category")
        videos = list_videos()
        if category:
            videos = [v for v in videos if v.get("category") == category]
        if not videos:
            return "知识库中没有视频" if not category else f"分类「{category}」下暂无视频", None
        lines = [
            f"- ID:{v['id']} 《{v['title']}》 分类:{v.get('category','未知')} 标签:{','.join((v.get('tags') or [])[:3])}"
            for v in videos
        ]
        return "\n".join(lines), None

    if name == "summarize_category":
        from processors.article import summarize_category_impl
        result = await loop.run_in_executor(None, summarize_category_impl, args.get("category", ""))
        return result, None

    if name == "compare_videos":
        from processors.article import compare_videos_impl
        result = await loop.run_in_executor(
            None, compare_videos_impl,
            args.get("video_ids", []), args.get("topic", ""),
        )
        return result, None

    if name == "search_youtube_videos":
        from extractors.youtube_search import search_youtube
        videos = await loop.run_in_executor(None, search_youtube, args.get("query", ""), 5)
        if not videos:
            return "未找到相关视频", None
        lines = [f"- {v['title']} | {v['url']} | 频道:{v['channel']}" for v in videos]
        return "\n".join(lines), videos

    if name == "generate_synthesis_article":
        from processors.article import generate_article
        result = await loop.run_in_executor(None, generate_article, args.get("topic", ""))
        if result.get("error"):
            return result["error"], None
        return (
            f"文章已生成并保存到 Obsidian（{result.get('source_count', 0)} 个来源）。\n\n"
            f"文章预览：\n\n{result.get('article', '')[:600]}…"
        ), None

    return "未知工具", None


# ── Chat endpoint ─────────────────────────────────────────────────────────────

@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    async_client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    async def generate() -> AsyncGenerator[str, None]:
        messages: list[dict] = [
            {"role": "system", "content": _CHAT_SYSTEM},
            *req.as_dicts(),
        ]
        messages = await _compress_history(messages, async_client)
        loop = asyncio.get_event_loop()

        for _ in range(8):
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
                if delta.content:
                    yield f"data: {json.dumps({'type': 'text', 'content': delta.content}, ensure_ascii=False)}\n\n"
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

            tool_call_list = [
                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in (tool_calls_acc[k] for k in sorted(tool_calls_acc))
            ]
            messages.append({"role": "assistant", "content": None, "tool_calls": tool_call_list})

            for tc in tool_call_list:
                tool_name = tc["function"]["name"]
                label = _TOOL_LABELS.get(tool_name, tool_name)
                yield f"data: {json.dumps({'type': 'tool_use', 'tool': tool_name, 'label': label}, ensure_ascii=False)}\n\n"

                result_str, suggestions = await _execute_tool(tool_name, tc["function"]["arguments"], loop)

                if suggestions:
                    yield f"data: {json.dumps({'type': 'suggestions', 'videos': suggestions}, ensure_ascii=False)}\n\n"

                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result_str})

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Article & Review endpoints ────────────────────────────────────────────────

@app.post("/api/generate-article")
async def generate_article_endpoint(req: ArticleRequest):
    loop = asyncio.get_event_loop()
    from processors.article import generate_article
    result = await loop.run_in_executor(None, generate_article, req.topic)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/articles")
async def get_articles():
    from processors.article import list_articles
    return list_articles()


@app.post("/api/review/generate")
async def generate_review(req: ReviewRequest):
    loop = asyncio.get_event_loop()
    from processors.review import generate_weekly_review
    result = await loop.run_in_executor(None, generate_weekly_review, req.days)
    return result


@app.post("/api/review/chat/stream")
async def review_chat_stream(req: ReviewChatRequest):
    async_client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    system = f"""\
你是用户的知识复盘助手，正在帮助用户深化这份复盘报告的价值。

当前复盘报告内容：
---
{req.review_content[:4000]}
---

你的职责：
1. 回答用户关于这份报告的任何问题
2. 帮助制定下一步具体可执行的学习计划
3. 深入展开报告中提到的某个知识点
4. 将行动清单转化为带时间节点的具体步骤
5. 识别本期学习中被忽视但值得关注的内容

回答要具体、可操作，用中文，每次回答不超过 400 字。"""

    async def generate() -> AsyncGenerator[str, None]:
        messages = [{"role": "system", "content": system}, *req.as_dicts()]
        stream = await async_client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            max_tokens=1024,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield f"data: {json.dumps({'type': 'text', 'content': content}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/reviews")
async def get_reviews():
    from processors.review import list_reviews
    return list_reviews()


@app.get("/api/recommendations")
async def get_recommendations():
    loop = asyncio.get_event_loop()
    from processors.recommendations import generate_recommendations
    result = await loop.run_in_executor(None, generate_recommendations)
    return result


# ── Stats endpoint ────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    from datetime import timedelta
    videos = list_videos()
    total = len(videos)
    total_duration = sum(v.get("duration", 0) or 0 for v in videos)

    categories: dict[str, int] = {}
    platforms: dict[str, int] = {}
    tag_count: dict[str, int] = {}
    for v in videos:
        cat = v.get("category") or "其他"
        categories[cat] = categories.get(cat, 0) + 1
        plat = v.get("platform") or "other"
        platforms[plat] = platforms.get(plat, 0) + 1
        for tag in v.get("tags") or []:
            if tag:
                tag_count[tag] = tag_count.get(tag, 0) + 1

    top_tags = [{"tag": t, "count": c} for t, c in sorted(tag_count.items(), key=lambda x: -x[1])[:15]]

    now = datetime.now()
    weekly = []
    for i in range(7, -1, -1):
        week_start = now - timedelta(weeks=i + 1)
        week_end = now - timedelta(weeks=i)
        count = 0
        for v in videos:
            try:
                ts = datetime.fromisoformat(v["created_at"])
                if week_start <= ts < week_end:
                    count += 1
            except Exception:
                pass
        weekly.append({"label": week_start.strftime("%m/%d"), "count": count})

    return {
        "total": total,
        "total_duration": total_duration,
        "categories": categories,
        "platforms": platforms,
        "top_tags": top_tags,
        "weekly": weekly,
    }


# ── Video library endpoints ───────────────────────────────────────────────────

@app.get("/api/videos/check")
async def check_duplicate(url: str):
    videos = list_videos()
    existing = next((v for v in videos if v.get("url") == url), None)
    if existing:
        return {"duplicate": True, "video": {k: v for k, v in existing.items() if k not in ("insights", "transcript")}}
    return {"duplicate": False}


@app.get("/api/videos")
async def get_videos():
    videos = list_videos()
    return [
        {k: v for k, v in video.items() if k not in ("insights", "transcript")}
        for video in videos
    ]


@app.get("/api/videos/{video_id}/note")
async def get_note(video_id: str):
    video = get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"insights": video.get("insights", "")}


@app.put("/api/videos/{video_id}/note")
async def update_note(video_id: str, req: NoteUpdateRequest, background_tasks: BackgroundTasks):
    video = get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, update_obsidian_note,
        video.get("obsidian_path", ""),
        video.get("title", ""),
        video.get("transcript", ""),
        req.insights,
    )
    update_video_note(video_id, req.insights)
    background_tasks.add_task(_reindex_note, video, req.insights)
    return {"ok": True}


@app.delete("/api/videos/{video_id}")
async def remove_video(video_id: str):
    videos = list_videos()
    video = next((v for v in videos if v.get("id") == video_id), None)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    delete_document(video["url"])
    deleted = delete_video(video_id)
    return {"deleted": deleted}


# ── Video processing endpoints ────────────────────────────────────────────────

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
