"""Nested span recording for the execution that is currently running.

Outside run_suite() nothing is recording, so @trace and span() cost almost nothing and never fail.
"""
import contextvars
import functools
import inspect
import time
from contextlib import contextmanager
from typing import Any, Callable, Optional

KINDS = ("root", "llm", "tool", "retrieval", "other")


class Recorder:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.spans: list = []
        self.depth = 1  # depth 0 is the request span added by run_suite

    def now_ms(self) -> float:
        return (time.perf_counter() - self.t0) * 1000


_current: contextvars.ContextVar = contextvars.ContextVar("eval_workbench_recorder", default=None)


class SpanHandle:
    def __init__(self, record: Optional[dict]) -> None:
        self._record = record

    def set(self, **attrs: Any) -> None:
        """Attach attributes to the span, such as token counts."""
        if self._record is not None:
            self._record["attrs"].update(attrs)


@contextmanager
def span(name: str, kind: str = "other", **attrs: Any):
    rec = _current.get()
    if rec is None:
        yield SpanHandle(None)
        return
    record = {"name": name, "kind": kind if kind in KINDS else "other", "start": round(rec.now_ms(), 1),
              "dur": 0, "depth": rec.depth, "attrs": dict(attrs)}
    rec.spans.append(record)
    rec.depth += 1
    try:
        yield SpanHandle(record)
    except BaseException as e:
        record["attrs"]["error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        rec.depth -= 1
        record["dur"] = round(rec.now_ms() - record["start"], 1)


def trace(fn: Optional[Callable] = None, *, name: Optional[str] = None, kind: str = "other"):
    """Record a span around a function. Use as @trace or @trace(name="llm.generate", kind="llm")."""

    def wrap(func: Callable) -> Callable:
        span_name = name or func.__name__
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def awrapper(*args, **kwargs):
                with span(span_name, kind):
                    return await func(*args, **kwargs)
            return awrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with span(span_name, kind):
                return func(*args, **kwargs)
        return wrapper

    return wrap(fn) if callable(fn) else wrap


def start_recording() -> tuple:
    rec = Recorder()
    return rec, _current.set(rec)


def stop_recording(token) -> None:
    _current.reset(token)
