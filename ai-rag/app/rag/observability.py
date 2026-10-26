"""RAG 请求级计时上下文。"""

import contextvars
import time

_TIMING_CONTEXT: contextvars.ContextVar[dict[str, float] | None] = contextvars.ContextVar(
    "rag_timing_context",
    default=None,
)


def set_timing_context(metrics: dict[str, float]):
    return _TIMING_CONTEXT.set(metrics)


def reset_timing_context(token) -> None:
    _TIMING_CONTEXT.reset(token)


def record_timing(name: str, started_at: float) -> None:
    """把一次子调用的耗时写入当前请求的计时上下文。"""
    metrics = _TIMING_CONTEXT.get()
    if metrics is not None:
        metrics[name] = round((time.perf_counter() - started_at) * 1000, 2)
