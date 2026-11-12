"""会话运行时状态（可持久化的 Checkpoint）。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent.message import Message


class RunStatus(str, Enum):
    IDLE = "IDLE"                          # 空闲，可接收新输入
    WAITING_APPROVAL = "WAITING_APPROVAL"  # 挂起，等待人工审批高危工具


@dataclass
class PendingApproval:
    step: int                              # 挂起时所在的推理步
    tool_call_ids: list[str]               # 需要审批的高危调用
    blocked_ids: list[str] = field(default_factory=list)       # 被护栏拦截的重复调用
    seen_signatures: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_record(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "tool_call_ids": self.tool_call_ids,
            "blocked_ids": self.blocked_ids,
            "seen_signatures": self.seen_signatures,
            "created_at": self.created_at,
        }

    @classmethod
    def from_record(cls, raw: dict[str, Any]) -> "PendingApproval":
        return cls(
            step=raw["step"],
            tool_call_ids=list(raw.get("tool_call_ids") or []),
            blocked_ids=list(raw.get("blocked_ids") or []),
            seen_signatures=list(raw.get("seen_signatures") or []),
            created_at=raw.get("created_at") or time.time(),
        )


@dataclass
class SessionState:
    session_id: str
    user_id: str = "default"
    messages: list[Message] = field(default_factory=list)   # 完整历史（含 tool_calls / tool），不含 system
    summary: str = ""                                       # L2 滚动摘要
    summarized_upto: int = 0                                # messages[:summarized_upto] 已并入摘要
    status: RunStatus = RunStatus.IDLE
    pending: PendingApproval | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_record(self) -> dict[str, Any]:
        return {
            "version": 2,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "status": self.status.value,
            "pending": self.pending.to_record() if self.pending else None,
            "summary": self.summary,
            "summarized_upto": self.summarized_upto,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [m.to_record() for m in self.messages],
        }

    @classmethod
    def from_record(cls, raw: dict[str, Any]) -> "SessionState":
        return cls(
            session_id=raw["session_id"],
            user_id=raw.get("user_id") or "default",
            messages=[Message.from_record(m) for m in raw.get("messages") or []],
            summary=raw.get("summary") or "",
            summarized_upto=int(raw.get("summarized_upto") or 0),
            status=RunStatus(raw.get("status") or RunStatus.IDLE.value),
            pending=PendingApproval.from_record(raw["pending"]) if raw.get("pending") else None,
            created_at=raw.get("created_at") or time.time(),
            updated_at=raw.get("updated_at") or time.time(),
        )
