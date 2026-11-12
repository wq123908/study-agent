"""Token 估算：优先使用 tiktoken（若已安装），否则按字符类别启发式估算。

启发式系数参考 DeepSeek 官方说明：1 个中文字符 ≈ 0.6 token，1 个英文字符 ≈ 0.3 token。
用于上下文预算控制已足够（预算本身会留有余量）。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Iterable

from agent.message import Message

_MESSAGE_OVERHEAD = 4  # 每条消息的角色/分隔符开销


@lru_cache(maxsize=1)
def _get_encoder():
    try:
        import tiktoken  # type: ignore

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - 未安装或离线无法下载词表时降级
        return None


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3000 <= code <= 0x303F
        or 0xFF00 <= code <= 0xFFEF
    )


def count_text_tokens(text: str | None) -> int:
    if not text:
        return 0
    encoder = _get_encoder()
    if encoder is not None:
        return len(encoder.encode(text))
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = len(text) - cjk
    return int(cjk * 0.6 + other * 0.3) + 1


def count_message_tokens(msg: Message) -> int:
    total = _MESSAGE_OVERHEAD + count_text_tokens(msg.content)
    for tc in msg.tool_calls:
        total += count_text_tokens(tc.name) + count_text_tokens(tc.arguments) + 3
    if msg.reasoning_content and msg.tool_calls:
        total += count_text_tokens(msg.reasoning_content)
    return total


def count_messages_tokens(messages: Iterable[Message]) -> int:
    return sum(count_message_tokens(m) for m in messages)
