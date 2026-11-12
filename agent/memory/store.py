"""L1 会话存储：抽象接口 + 本地 JSON 文件实现（原子写入）。

生产环境可实现同一接口的 RedisSessionStore / PostgresSessionStore 进行替换。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

from agent.message import SYSTEM, Message
from agent.state import SessionState

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class InvalidSessionId(ValueError):
    pass


def validate_session_id(session_id: str) -> str:
    if not _SESSION_ID_RE.match(session_id or ""):
        raise InvalidSessionId("session_id 只能包含字母、数字、下划线和短横线，长度 1~64")
    return session_id


class SessionStore(Protocol):
    async def load(self, session_id: str) -> SessionState | None: ...
    async def save(self, state: SessionState) -> None: ...
    async def delete(self, session_id: str) -> bool: ...
    async def list_ids(self) -> list[str]: ...


class JsonFileSessionStore:
    """每个会话一个 JSON 文件；写入采用 临时文件 + os.replace，避免进程崩溃导致文件损坏。"""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def _path(self, session_id: str) -> Path:
        return self.directory / f"{validate_session_id(session_id)}.json"

    def _load_sync(self, session_id: str) -> SessionState | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        return SessionState.from_record(json.loads(path.read_text(encoding="utf-8")))

    def _save_sync(self, state: SessionState) -> None:
        path = self._path(state.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(state.to_record(), ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{state.session_id}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _delete_sync(self, session_id: str) -> bool:
        path = self._path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    async def load(self, session_id: str) -> SessionState | None:
        return await asyncio.to_thread(self._load_sync, session_id)

    async def save(self, state: SessionState) -> None:
        await asyncio.to_thread(self._save_sync, state)

    async def delete(self, session_id: str) -> bool:
        return await asyncio.to_thread(self._delete_sync, session_id)

    async def list_ids(self) -> list[str]:
        if not self.directory.exists():
            return []
        return sorted(p.stem for p in self.directory.glob("*.json"))


class InMemorySessionStore:
    """测试与临时会话使用。"""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    async def load(self, session_id: str) -> SessionState | None:
        raw = self._data.get(validate_session_id(session_id))
        return SessionState.from_record(json.loads(json.dumps(raw))) if raw else None

    async def save(self, state: SessionState) -> None:
        self._data[validate_session_id(state.session_id)] = state.to_record()

    async def delete(self, session_id: str) -> bool:
        return self._data.pop(session_id, None) is not None

    async def list_ids(self) -> list[str]:
        return sorted(self._data)


def load_legacy_messages(path: str | Path) -> list[Message]:
    """读取 v0.1 版本的 memory.json（[{role, content}]），丢弃 system 消息（system 改为运行时注入）。"""
    path = Path(path)
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Message.from_record(item) for item in raw if item.get("role") != SYSTEM]
