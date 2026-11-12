"""结构化日志：自动附带 trace_id / session_id，支持文本或 JSON 输出。"""
from __future__ import annotations

import json
import logging
import os

from agent.observability.tracer import current_trace


class TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        trace = current_trace()
        record.trace_id = trace.trace_id[:12] if trace else "-"
        record.session_id = trace.session_id if trace else "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", "-"),
            "session_id": getattr(record, "session_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str | None = None, json_format: bool | None = None) -> None:
    level = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    if json_format is None:
        json_format = (os.getenv("LOG_FORMAT") or "").lower() == "json"

    handler = logging.StreamHandler()
    handler.addFilter(TraceContextFilter())
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(trace_id)s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        ))

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
