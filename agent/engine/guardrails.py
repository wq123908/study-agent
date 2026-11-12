"""护栏：输入校验、重复工具调用检测（防死循环）。"""
from __future__ import annotations

import hashlib
import json
from typing import Iterable

from agent.message import ToolCallItem


def tool_signature(call: ToolCallItem) -> str:
    """(工具名, 规范化参数) 的哈希；参数按 key 排序，忽略空白差异。"""
    try:
        canonical = json.dumps(json.loads(call.arguments or "{}"), sort_keys=True, ensure_ascii=False)
    except json.JSONDecodeError:
        canonical = (call.arguments or "").strip()
    return hashlib.sha256(f"{call.name}\x00{canonical}".encode("utf-8")).hexdigest()[:32]


class LoopGuard:
    """同一次运行内，完全相同的工具调用只允许执行一次。

    重复调用不会被执行，而是回填一条护栏提示作为 tool 结果（保持协议合法），
    累计违规达到 max_violations 次后，引擎将停止工具调用并强制模型给出最终回答。
    """

    def __init__(self, seen: Iterable[str] = (), max_violations: int = 2) -> None:
        self.seen: set[str] = set(seen)
        self.max_violations = max_violations
        self.violations = 0

    def check(self, calls: list[ToolCallItem]) -> set[str]:
        """返回被判定为重复的 tool_call_id 集合，并登记新签名。"""
        duplicated: set[str] = set()
        for call in calls:
            sig = tool_signature(call)
            if sig in self.seen:
                duplicated.add(call.id)
            else:
                self.seen.add(sig)
        if duplicated:
            self.violations += 1
        return duplicated

    @property
    def tripped(self) -> bool:
        return self.violations >= self.max_violations


def validate_user_input(text: str, max_chars: int) -> str | None:
    """返回错误描述；合法则返回 None。"""
    if not text or not text.strip():
        return "输入不能为空"
    if len(text) > max_chars:
        return f"输入过长（{len(text)} 字符），上限 {max_chars} 字符"
    return None
