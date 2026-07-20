from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4

logger = logging.getLogger("mezo.trace")
_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)
_span_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("span_id", default=None)
_SENSITIVE_WORDS = (
    "authorization", "credential", "password", "private", "prompt", "secret", "token"
)


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str


@dataclass(frozen=True)
class SpanRecord:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    duration_seconds: float
    outcome: str
    attributes: dict[str, str]


def current_trace() -> TraceContext | None:
    trace_id = _trace_id.get()
    span_id = _span_id.get()
    return TraceContext(trace_id, span_id) if trace_id and span_id else None


@contextmanager
def tracing_boundary(
    name: str,
    attributes: Mapping[str, object] | None = None,
    trace_id: str | None = None,
) -> Iterator[TraceContext]:
    parent_span = _span_id.get()
    resolved_trace = _normalized_trace_id(trace_id or _trace_id.get())
    resolved_span = uuid4().hex[:16]
    trace_token = _trace_id.set(resolved_trace)
    span_token = _span_id.set(resolved_span)
    started = time.perf_counter()
    outcome = "ok"
    try:
        yield TraceContext(resolved_trace, resolved_span)
    except BaseException:
        outcome = "error"
        raise
    finally:
        record = SpanRecord(
            name=name[:128],
            trace_id=resolved_trace,
            span_id=resolved_span,
            parent_span_id=parent_span,
            duration_seconds=max(time.perf_counter() - started, 0.0),
            outcome=outcome,
            attributes=_safe_attributes(attributes or {}),
        )
        logger.info(
            json.dumps(
                {"event": "trace_boundary", **record.__dict__},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        _span_id.reset(span_token)
        _trace_id.reset(trace_token)


def _safe_attributes(attributes: Mapping[str, object]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in attributes.items():
        normalized = key.lower()
        if any(word in normalized for word in _SENSITIVE_WORDS):
            safe[key[:128]] = "[redacted]"
        else:
            safe[key[:128]] = str(value)[:500]
    return safe


def _normalized_trace_id(value: str | None) -> str:
    if not value:
        return uuid4().hex
    normalized = value.replace("-", "").lower()
    if len(normalized) == 32 and all(character in "0123456789abcdef" for character in normalized):
        return normalized
    return hashlib.sha256(value.encode()).hexdigest()[:32]
