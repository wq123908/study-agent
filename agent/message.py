from __future__ import annotations

import time
from dataclasses import dataclass,field
from typing import Any

SYSTEM,USER,ASSISTANT,TOOL = "system","user","assistant","tool" 

@dataclass
class ToolCallItem:
    id:str
    name:str
    arguments:str ="{}"

    def to_openai_dict(self) -> dict[str,Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }
    
    @classmethod
    def from_openai_dict(cls,raw:dict[str,Any]) -> ToolCallItem:
        function = raw.get("function") or {}
        return cls(
            id=raw.get("id", ""),
            name=function.get("name", raw.get("name", "")),
            arguments=function.get("arguments", raw.get("arguments", "{}")) or "{}",
        )
    
@dataclass
class Message:
    role:str
    content:str | None = None
    tool_calls:list[ToolCallItem] = field(default_factory=list)
    tool_call_id:str | None = None
    name:str | None = None
    reasoning_content: str | None = None    # 推理模型的思考过程（DeepSeek 等）
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content or ""}
        if self.role == ASSISTANT and self.tool_calls:
            payload["tool_calls"] = [tc.to_openai_dict() for tc in self.tool_calls]
            if self.reasoning_content:      # 工具循环内部分推理模型要求回传思考过程
                payload["reasoning_content"] = self.reasoning_content
        if self.role == TOOL:
            payload["tool_call_id"] = self.tool_call_id or ""
        return payload

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            record["tool_calls"] = [tc.to_openai_dict() for tc in self.tool_calls]
        if self.tool_call_id:
            record["tool_call_id"] = self.tool_call_id
        if self.name:
            record["name"] = self.name                  # 落盘保留工具名，方便审计与检索
        if self.reasoning_content:
            record["reasoning_content"] = self.reasoning_content
        record["created_at"] = self.created_at          # 保留精确时间戳，供 L2 摘要与排序使用
        if self.metadata:
            record["metadata"] = self.metadata
        return record

    @classmethod
    def from_record(cls,raw:dict[str,Any]) -> Message:
        return cls(
            role=raw["role"],
            content=raw.get("content"),
            tool_calls=[ToolCallItem.from_openai_dict(tc) for tc in raw.get("tool_calls") or []],
            tool_call_id=raw.get("tool_call_id"),
            name=raw.get("name"),
            reasoning_content=raw.get("reasoning_content"),
            created_at=raw.get("created_at") or time.time(),
            metadata=raw.get("metadata") or {},
        )


    def __str__(self) -> str:
        if self.tool_calls:
            calls = ", ".join(f"{tc.name}({tc.arguments})" for tc in self.tool_calls)
            return f"[{self.role}] -> {calls}"
        return f"[{self.role}] {self.content or ''}"