"""轻量级全链路追踪：Trace → Span 树，基于 contextvars 透传并支持导出。"""

from __future__ import annotations

import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any

_current_trace: ContextVar["Trace | None"] = ContextVar(
    "current_trace",
    default=None,
)
_current_span: ContextVar["Span | None"] = ContextVar(
    "current_span",
    default=None,
)

def _new_id() -> str:
    return uuid.uuid4().hex[:16]

@dataclass
class Span:
    kind: str
    name: str
    trace_id: str
    parent_id: str | None = None
    span_id: str = field(default_factory=_new_id)
    start: float = field(default_factory=time.time)
    end: float | None = None
    input: Any = None
    output: Any = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.end is None:
            return None
        return round((self.end - self.start) * 1000, 2)
    def update(
        self,
        output: Any = None,
        **attributes: Any,
    ) -> None:
        if output is not None:
            self.output = output
        self.attributes.update(attributes)
    def set_error(self, error: str) -> None:
        self.status = "error"
        self.error = error
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["duration_ms"] = self.duration_ms
        return data

@dataclass
class Trace:
    name: str
    session_id: str = ""
    user_id: str = ""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    start: float = field(default_factory=time.time)
    end: float | None = None
    input: Any = None
    output: Any = None
    status: str = "ok"
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)
    _lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
        compare=False,
    )

    def add_span(self, sp: Span) -> None:
        with self._lock:
            self.spans.append(sp)

    def add_usage(self, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        with self._lock:
            for key, value in usage.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self.usage[key] = self.usage.get(key, 0) + int(value)
    @property
    def duration_ms(self) -> float | None:
        if self.end is None:
            return None
        return round((self.end - self.start) * 1000, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "name": self.name,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "start": self.start,
            "end": self.end,
            "duration_ms": self.duration_ms,
            "input": self.input,
            "output": self.output,
            "status": self.status,
            "error": self.error,
            "usage": self.usage,
            "attributes": self.attributes,
            "spans": [s.to_dict() for s in self.spans],
        }