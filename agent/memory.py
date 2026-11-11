import json
from pathlib import Path

from agent.message import Message

class Memory:
    def __init__(self, path: str ="memory.json") -> None:
        self.path = Path(path)
    
    def load(self) -> list[Message]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [
            Message(role=item["role"], content=item["content"])
            for item in raw
        ]
    
    def save(self, messages: list[Message]) -> None:
        raw = [message.to_dict() for message in messages]
        self.path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
    
    def trim(self, messages: list[Message], max_count: int = 40) -> list[Message]:
        if len(messages) <= max_count:
            return messages
        head = messages[:1]                              # 永远保留第 0 条 system
        tail = messages[-(max_count - 1):]               # 保留最近的若干条
        return head + tail

