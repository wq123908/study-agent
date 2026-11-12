"""HTTP 接口请求与响应模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(default="default", pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    user_id: str = Field(default="default", max_length=64)
    message: str = Field(..., min_length=1, max_length=8000)


class ApproveRequest(BaseModel):
    session_id: str = Field(default="default", pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    user_id: str = Field(default="default", max_length=64)
    approve: bool | None = Field(default=None, description="全部批准(True)或全部拒绝(False)")
    decisions: dict[str, bool] | None = Field(default=None, description="按 tool_call_id 单独指定批准/拒绝")
    stream: bool = Field(default=True, description="是否以 SSE 流式返回")


class ChatResponse(BaseModel):
    status: str
    content: str = ""
    steps: int = 0
    truncated: bool = False
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    pending_tools: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    duration_ms: float | None = None
    error: dict[str, Any] | None = None
