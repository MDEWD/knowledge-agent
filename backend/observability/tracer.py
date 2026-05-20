"""
LangFuse observability wrapper.
Gracefully degrades to no-ops when LANGFUSE_* env vars are absent.
"""
from __future__ import annotations

import time
from typing import Any

from config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL

_enabled = bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)
_lf = None

if _enabled:
    try:
        from langfuse import Langfuse
        _lf = Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            host=LANGFUSE_BASE_URL,
        )
    except Exception as e:
        print(f"[tracer] LangFuse init failed, running without tracing: {e}")
        _enabled = False


# ── Lightweight wrappers ───────────────────────────────────────────────────────

class _NoopSpan:
    def __init__(self): self._start = time.time()
    def end(self, output: Any = None, usage: dict | None = None): pass
    @property
    def latency_ms(self) -> float: return (time.time() - self._start) * 1000


class _NoopTrace:
    id = "noop"
    def span(self, **kwargs): return _NoopSpan()
    def generation(self, **kwargs): return _NoopSpan()
    def update(self, **kwargs): pass


class Tracer:
    """
    Thin wrapper around LangFuse.

    Usage:
        trace = tracer.trace("chat", session_id="abc")
        gen = tracer.generation(trace, "llm-call", input_tokens=100)
        gen.end(output="...", output_tokens=50)
        tool = tracer.span(trace, "tool:search_kb", {"query": "..."})
        tool.end(output="3 results")
    """

    def trace(self, name: str, session_id: str | None = None, metadata: dict | None = None):
        if not _enabled or _lf is None:
            return _NoopTrace()
        try:
            return _lf.trace(
                name=name,
                session_id=session_id,
                metadata=metadata or {},
            )
        except Exception:
            return _NoopTrace()

    def generation(self, trace, name: str, model: str = "", input_tokens: int = 0,
                   input_text: str = ""):
        if not _enabled or not hasattr(trace, "generation"):
            return _NoopSpan()
        try:
            return trace.generation(
                name=name,
                model=model,
                usage={"input": input_tokens},
                input=input_text[:2000],
                start_time=None,
            )
        except Exception:
            return _NoopSpan()

    def span(self, trace, name: str, input_data: Any = None):
        if not _enabled or not hasattr(trace, "span"):
            return _NoopSpan()
        try:
            return trace.span(name=name, input=input_data)
        except Exception:
            return _NoopSpan()

    def end_generation(self, gen, output_text: str = "", output_tokens: int = 0,
                       input_tokens: int = 0):
        if not _enabled:
            return
        try:
            gen.end(
                output=output_text[:2000],
                usage={"input": input_tokens, "output": output_tokens, "total": input_tokens + output_tokens},
            )
        except Exception:
            pass

    def end_span(self, span, output: Any = None):
        if not _enabled:
            return
        try:
            span.end(output=output)
        except Exception:
            pass

    def flush(self):
        if _enabled and _lf is not None:
            try:
                _lf.flush()
            except Exception:
                pass

    @property
    def enabled(self) -> bool:
        return _enabled


tracer = Tracer()
