from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

TraceSink = Callable[..., None]

_trace_id: ContextVar[str | None] = ContextVar("memora_trace_id", default=None)
_trace_sink: ContextVar[TraceSink | None] = ContextVar("memora_trace_sink", default=None)


@contextmanager
def trace_context(trace_id: str, sink: TraceSink) -> Iterator[None]:
    id_token = _trace_id.set(trace_id)
    sink_token = _trace_sink.set(sink)
    try:
        yield
    finally:
        _trace_id.reset(id_token)
        _trace_sink.reset(sink_token)


def current_trace_id() -> str | None:
    return _trace_id.get()


def emit_trace_event(
    *,
    stage: str,
    event: str,
    status: str,
    attempt: int | None = None,
    duration_ms: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    trace_id = _trace_id.get()
    sink = _trace_sink.get()
    if not trace_id or not sink:
        return
    sink(
        trace_id,
        stage=stage,
        event=event,
        status=status,
        attempt=attempt,
        duration_ms=duration_ms,
        metadata=metadata or {},
    )
