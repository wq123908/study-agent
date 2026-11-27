"""结构化任务输入契约：统一自然语言文本与结构化参数，并在入口完成强校验。"""
from __future__ import annotations

import copy
import json
import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent.memory.store import validate_session_id

TASK_REQUEST_VERSION = 1

def _new_request_id() -> str:
    """生成带前缀的稳定请求标识，便于区分同一会话下的不同任务委托。"""
    return f"req_{uuid.uuid4().hex[:16]}"

def _ensure_json_dict(
    value: Any,
    field_name: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} 必须是字典对象")
    try:
        # allow_nan=False 同时拦截 NaN/Infinity 及不可 JSON 编码的内存对象
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 包含无法 JSON 编码的值: {exc}") from exc
    return json.loads(encoded)

class TaskRequest(BaseModel):
    """一次可执行任务的输入委托单（只承载纯粹可序列化数据，不含运行时依赖或权限身份）。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    request_id: str = Field(default_factory=_new_request_id)
    text: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    version: int = Field(
        default=TASK_REQUEST_VERSION,
        ge=1,
    )

    @field_validator("session_id")
    @classmethod
    def _check_session_id(cls, value: str) -> str:
        return validate_session_id(value.strip())

    @field_validator("request_id")
    @classmethod
    def _check_request_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("request_id 不能为空")
        return cleaned

    @field_validator("text")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("params")
    @classmethod
    def _check_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _ensure_json_dict(
            value,
            "params",
        )

    @field_validator("metadata")
    @classmethod
    def _check_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _ensure_json_dict(
            value,
            "metadata",
        )

    @model_validator(mode="after")
    def _require_text_or_params(self) -> TaskRequest:
        if self.text is None and not self.params:
            raise ValueError("任务输入不能为空：text 与 params 至少提供一项")
        return self

    def to_record(self) -> dict[str, Any]:
        """导出可 JSON 序列化的深拷贝字典，防止外部修改污染原请求对象。"""
        return copy.deepcopy(self.model_dump(mode="json"))

    @classmethod
    def from_record(cls, raw: dict[str, Any]) -> TaskRequest:
        """从持久化字典严格恢复任务请求；缺失关键标识或非法字段立刻抛错。"""
        if not isinstance(raw, dict):
            raise ValueError("任务请求记录必须是字典对象")
        if not isinstance(raw.get("request_id"), str) or not raw["request_id"].strip():
            raise ValueError("任务请求记录缺少有效的 request_id")
        if isinstance(raw.get("created_at"), bool) or not isinstance(
            raw.get("created_at"),
            (int, float),
        ):
            raise ValueError("任务请求记录缺少有效的 created_at")
        return cls.model_validate(raw)