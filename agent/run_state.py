"""独立运行记录：描述一次任务从创建、执行、等待到终态的独立生命周期。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

RUN_RECORD_VERSION = 1

def _new_run_id() -> str:
    """生成带前缀的稳定运行标识，便于在日志中与 trace_id 区分。"""
    return f"run_{uuid.uuid4().hex[:16]}"

def _require_non_empty_str(
    raw: dict[str, Any],
    key: str,
) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"运行记录缺少有效的 {key}")
    return value.strip()

def _require_timestamp(
    raw: dict[str, Any],
    key: str,
) -> float:
    value = raw.get(key)
    # Python 中 bool 是 int 的子类，显式排除 True/False 被误当成时间戳
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"运行记录缺少有效的时间戳 {key}: {value!r}")
    return float(value)

class RunPhase(str, Enum):
    """一次任务执行的生命周期阶段（与 SessionState.RunStatus 并列演进）。"""

    CREATED = "CREATED"        # 已接收任务，尚未开始执行
    RUNNING = "RUNNING"        # 正在执行推理或工具调用
    WAITING = "WAITING"        # 挂起等待（如人工审批、补输入或外部信号）
    COMPLETED = "COMPLETED"    # 程序正常走到终点（任务成败由 13.3 结果契约判定）
    FAILED = "FAILED"          # 执行因不可恢复异常中止
    CANCELLED = "CANCELLED"    # 收到取消请求后终止

@dataclass
class RunRecord:
    """单次运行的独立记录：同一会话下的多次运行各自持有独立标识、阶段与时间戳。"""

    session_id: str
    run_id: str = field(default_factory=_new_run_id)
    version: int = RUN_RECORD_VERSION
    phase: RunPhase = RunPhase.CREATED
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("session_id 不能为空")
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id 不能为空")
        self.session_id = self.session_id.strip()
        self.run_id = self.run_id.strip()
        if not isinstance(self.phase, RunPhase):
            try:
                self.phase = RunPhase(self.phase)
            except ValueError as exc:
                raise ValueError(f"无效的运行阶段: {self.phase!r}") from exc

    def to_record(self) -> dict[str, Any]:
        """导出可 JSON 序列化的持久化字典，显式携带记录版本号。"""
        return {
            "version": self.version,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "phase": self.phase.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_record(cls, raw: dict[str, Any]) -> RunRecord:
        """从持久化字典严格恢复原运行记录；缺失关键标识或非法阶段立刻抛错。"""
        if not isinstance(raw, dict):
            raise ValueError("运行记录必须是字典对象")

        run_id = _require_non_empty_str(
            raw,
            "run_id",
        )
        session_id = _require_non_empty_str(
            raw,
            "session_id",
        )
        raw_phase = raw.get("phase")
        if not isinstance(raw_phase, str):
            raise ValueError(f"无效的运行阶段: {raw_phase!r}")
        try:
            phase = RunPhase(raw_phase)
        except ValueError as exc:
            raise ValueError(f"无效的运行阶段: {raw_phase!r}") from exc

        created_at = _require_timestamp(
            raw,
            "created_at",
        )
        updated_at = (
            _require_timestamp(
                raw,
                "updated_at",
            )
            if "updated_at" in raw
            else created_at
        )
        raw_version = raw.get(
            "version",
            RUN_RECORD_VERSION,
        )
        if (
            isinstance(raw_version, bool)
            or not isinstance(raw_version, int)
            or raw_version < 1
        ):
            raise ValueError(f"无效的记录版本: {raw_version!r}")

        return cls(
            session_id=session_id,
            run_id=run_id,
            phase=phase,
            created_at=created_at,
            updated_at=updated_at,
            version=raw_version,
        )               