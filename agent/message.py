from dataclasses import dataclass

SYSTEM = "system"
USER = "user"
ASSISTANT = "assistant"

@dataclass
class Message:
    role: str
    content: str
    
    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}
    
    def __str__(self) -> str:
        return f"[{self.role}] {self.content}"
