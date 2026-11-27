"""任务结果契约：表达业务成败、结构化错误与产物引用，并与运行阶段清晰解耦。"""
from __future__ import annotations

import copy
import json
import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent.run_state import RunPhase

TASK_RESULT_VERSION = 1

def _new_artifact_id() -> str:
    """生成带前缀的稳定产物标识。"""
    return f"art_{uuid.uuid4().hex[:16]}"

def _ensure_json_dict(
    value: Any,
    field_name: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} 必须是字典对象")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 包含无法 JSON 编码的值: {exc}") from exc
    return json.loads(encoded)

class TaskOutcome(str, Enum):
    """任务业务结果（区别于 RunPhase 执行阶段，也区别于阶段 17 的回复评分）。"""

    SUCCEEDED = "SUCCEEDED"                    # 满足任务成功条件
    PARTIAL = "PARTIAL"                        # 部分步骤完成，仍有未完成项
    FAILED = "FAILED"                          # 未满足成功条件或执行失败
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"  # 副作用状态不确定，需人工或对账核验

class TaskError(BaseModel):
    """结构化错误：保留机器错误码、可读说明、失败来源与是否可重试。"""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    source: str = "engine"
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "code",
        "message",
        "source",
    )
    @classmethod
    def _non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("错误字段不能为空")
        return cleaned

    @field_validator("details")
    @classmethod
    def _check_details(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _ensure_json_dict(
            value,
            "details",
        )

class ArtifactRef(BaseModel):
    """产物提货凭证：描述产物标识、类型与定位，正文读取交由后续访问策略控制。"""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(default_factory=_new_artifact_id)
    kind: str
    locator: str
    media_type: str = "text/plain"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "artifact_id",
        "kind",
        "locator",
        "media_type",
    )
    @classmethod
    def _non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("产物引用字段不能为空")
        return cleaned

    @field_validator("metadata")
    @classmethod
    def _check_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _ensure_json_dict(
            value,
            "metadata",
        )

class TaskResult(BaseModel):
    """单次任务的结果契约：绑定所属 run_id，强制校验阶段与结果间不能自相矛盾。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    outcome: TaskOutcome
    run_phase: RunPhase = RunPhase.COMPLETED
    text: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    error: TaskError | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    version: int = Field(
        default=TASK_RESULT_VERSION,
        ge=1,
    )

    @field_validator("run_id")
    @classmethod
    def _check_run_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("run_id 不能为空")
        return cleaned

    @field_validator("data")
    @classmethod
    def _check_data(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _ensure_json_dict(
            value,
            "data",
        )

    @model_validator(mode="after")
    def _check_consistency(self) -> TaskResult:
        if self.outcome is TaskOutcome.SUCCEEDED:
            if self.error is not None:
                raise ValueError("成功结果不能同时携带 error")
            if self.run_phase in (RunPhase.FAILED, RunPhase.CANCELLED):
                raise ValueError(
                    f"执行阶段为 {self.run_phase.value} 时，任务结果不能为 SUCCEEDED"
                )
        elif self.outcome is TaskOutcome.FAILED:
            if self.error is None:
                raise ValueError("失败结果必须提供结构化 error")
        elif self.outcome is TaskOutcome.NEEDS_VERIFICATION:
            if self.error is None and not (self.text and self.text.strip()):
                raise ValueError("待核对结果必须提供 error 或 text 说明核对原因")

        seen_ids: set[str] = set()
        for ref in self.artifacts:
            if ref.artifact_id in seen_ids:
                raise ValueError(f"产物引用 ID 重复: {ref.artifact_id}")
            seen_ids.add(ref.artifact_id)
        return self

    def to_record(self) -> dict[str, Any]:
        """导出可 JSON 序列化的深拷贝字典。"""
        return copy.deepcopy(self.model_dump(mode="json"))

    @classmethod
    def from_record(cls, raw: dict[str, Any]) -> TaskResult:
        """从持久化字典严格恢复任务结果；缺失关键标识或出现矛盾状态立刻抛错。"""
        if not isinstance(raw, dict):
            raise ValueError("任务结果记录必须是字典对象")
        if not isinstance(raw.get("run_id"), str) or not raw["run_id"].strip():
            raise ValueError("任务结果记录缺少有效的 run_id")
        if isinstance(raw.get("created_at"), bool) or not isinstance(
            raw.get("created_at"),
            (int, float),
        ):
            raise ValueError("任务结果记录缺少有效的 created_at")
        return cls.model_validate(raw)
