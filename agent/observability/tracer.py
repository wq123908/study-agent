"""轻量级全链路追踪：Trace → Span 树，基于 contextvars 透传并支持导出。"""

from __future__ import annotations

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