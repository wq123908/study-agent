"""引擎事件协议：CLI 与 SSE 共用。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# 事件类型常量：把引擎运行全过程拆成标准进度小纸条
RUN_START = "run_start"
STEP_START = "step_start"
THINKING_DELTA = "thinking_delta"
CONTENT_DELTA = "content_delta"
TOOL_CALL_START = "tool_call_start"
TOOL_CALL_RESULT = "tool_call_result"
APPROVAL_REQUIRED = "approval_required"
APPROVAL_RESOLVED = "approval_resolved"
DONE = "done"
ERROR = "error"

@dataclass
class AgentEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            **self.data,
        }

    def to_sse(self) -> str:
        """按标准 SSE 协议序列化：event 行 + data 行 + 空行分隔。"""
        payload = json.dumps(
            self.data,
            ensure_ascii=False,
            default=str,
        )
        return f"event: {self.type}\ndata: {payload}\n\n"


def error_event(
    code: str,
    message: str,
    **extra: Any,
) -> AgentEvent:
    return AgentEvent(
        type=ERROR,
        data={
            "code": code,
            "message": message,
            **extra,
        },
    )