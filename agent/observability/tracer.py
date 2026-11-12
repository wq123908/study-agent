"""轻量级全链路追踪：Trace → Span 树，基于 contextvars 透传，导出到 JSONL（可扩展到 Langfuse/OTel）。

层级约定::

    Trace(agent.run)
      ├─ Span(memory)   build_context
      ├─ Span(step)     step-1
      │    ├─ Span(llm)   generation（含 TTFT、usage）
      │    └─ Span(tool)  calculator / get_current_time ...（并发）
      └─ Span(step)     step-2 ...
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Protocol

logger = logging.getLogger(__name__)

_current_trace: ContextVar["Trace | None"] = ContextVar("current_trace", default=None)
_current_span: ContextVar["Span | None"] = ContextVar("current_span", default=None)


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
        return None if self.end is None else round((self.end - self.start) * 1000, 2)

    def update(self, output: Any = None, **attributes: Any) -> None:
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
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

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
        return None if self.end is None else round((self.end - self.start) * 1000, 2)

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


# ---------------------------------------------------------------------- 导出器
class TraceExporter(Protocol):
    def export(self, trace: Trace) -> None: ...


class JsonlTraceExporter:
    """每条 Trace 一行 JSON，按日期分文件：data/traces/2026-11-12.jsonl"""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self._lock = threading.Lock()

    def export(self, trace: Trace) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{datetime.fromtimestamp(trace.start):%Y-%m-%d}.jsonl"
        line = json.dumps(trace.to_dict(), ensure_ascii=False, default=str)
        with self._lock, path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


class InMemoryTraceExporter:
    def __init__(self) -> None:
        self.traces: list[Trace] = []

    def export(self, trace: Trace) -> None:
        self.traces.append(trace)


class Tracer:
    def __init__(self, exporters: list[TraceExporter] | None = None) -> None:
        self.exporters = exporters or []

    def start_trace(self, name: str, *, session_id: str = "", user_id: str = "", input: Any = None) -> Trace:
        return Trace(name=name, session_id=session_id, user_id=user_id, input=input)

    def finish_trace(self, trace: Trace, *, output: Any = None, error: str | None = None) -> None:
        if trace.end is not None:
            return
        trace.end = time.time()
        if output is not None:
            trace.output = output
        if error:
            trace.status, trace.error = "error", error
        for exporter in self.exporters:
            try:
                exporter.export(trace)
            except Exception:  # noqa: BLE001 - 观测失败绝不能影响业务
                logger.exception("Trace 导出失败")


# ---------------------------------------------------------------------- 上下文 API
def current_trace() -> Trace | None:
    return _current_trace.get()


def current_trace_id() -> str:
    trace = _current_trace.get()
    return trace.trace_id if trace else "-"


def activate_trace(trace: Trace | None):
    """把 trace 设为当前上下文的 Trace，返回 token（可用于 deactivate）。"""
    return _current_trace.set(trace), _current_span.set(None)


def deactivate_trace(tokens) -> None:
    trace_token, span_token = tokens
    try:
        _current_span.reset(span_token)
        _current_trace.reset(trace_token)
    except ValueError:
        # 异步生成器可能在不同的 Context 中被关闭，此时直接清空即可
        _current_span.set(None)
        _current_trace.set(None)


@contextmanager
def span(kind: str, name: str, input: Any = None, **attributes: Any) -> Iterator[Span]:
    """在当前 Trace 下创建子 Span；没有活动 Trace 时退化为空操作（仍返回可写的 Span）。"""
    trace = _current_trace.get()
    parent = _current_span.get()
    sp = Span(
        kind=kind,
        name=name,
        trace_id=trace.trace_id if trace else "-",
        parent_id=parent.span_id if parent else None,
        input=input,
        attributes=dict(attributes),
    )
    token = _current_span.set(sp)
    try:
        yield sp
    except GeneratorExit:
        sp.status = "cancelled"     # 消费方提前断开（如客户端关闭 SSE）
        raise
    except BaseException as exc:
        sp.set_error(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        sp.end = time.time()
        try:
            _current_span.reset(token)
        except ValueError:
            _current_span.set(parent)
        if trace is not None:
            trace.add_span(sp)
