"""强类型配置：集中读取环境变量，并在启动时做校验。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """配置缺失或非法。"""


def _env_str(name: str, default: str = "") -> str:
    # 修复基线 Bug：os.getenv(...) 可能返回 None，必须给默认值再 strip
    return (os.getenv(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env_str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"环境变量 {name} 必须是整数，当前值: {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = _env_str(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"环境变量 {name} 必须是数字，当前值: {raw!r}") from exc


def _env_list(name: str) -> list[str]:
    return [item.strip() for item in _env_str(name).split(",") if item.strip()]


@dataclass
class Config:
    # ---- 模型 ----
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    fallback_model: str = ""              # 主模型重试耗尽后的备用模型（留空则不降级）
    temperature: float = 0.3
    request_timeout: float = 60.0
    max_retries: int = 3

    # ---- Agent 引擎 ----
    max_steps: int = 8
    max_input_chars: int = 8000
    tool_timeout: float = 15.0
    tool_max_concurrency: int = 5
    tool_max_output_chars: int = 4000

    # ---- 记忆 ----
    context_max_tokens: int = 6000        # 发给模型的上下文 Token 预算
    summary_trigger_tokens: int = 1500    # 滑出窗口且未摘要的消息超过该值时触发滚动摘要
    long_term_top_k: int = 3

    # ---- 存储与观测 ----
    data_dir: Path = field(default_factory=lambda: Path("data"))

    # ---- 服务 ----
    api_keys: list[str] = field(default_factory=list)  # 为空表示不鉴权（仅限本地开发）

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def traces_dir(self) -> Path:
        return self.data_dir / "traces"

    @property
    def workspace_dir(self) -> Path:
        return self.data_dir / "workspace"

    @property
    def long_term_path(self) -> Path:
        return self.data_dir / "long_term_memory.json"

    def validate(self) -> "Config":
        if self.max_steps < 1:
            raise ConfigError("AGENT_MAX_STEPS 必须 >= 1")
        if self.context_max_tokens < 500:
            raise ConfigError("CONTEXT_MAX_TOKENS 过小（至少 500）")
        if not 0.0 <= self.temperature <= 2.0:
            raise ConfigError("LLM_TEMPERATURE 必须在 0~2 之间")
        return self


def load_config(require_api_key: bool = True) -> Config:
    api_key = _env_str("DEEPSEEK_API_KEY")
    if require_api_key and (not api_key or api_key.startswith("sk-your-key")):
        raise ConfigError("请在项目根目录 .env 中填写真实的 DEEPSEEK_API_KEY")

    return Config(
        api_key=api_key,
        base_url=_env_str("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=_env_str("DEEPSEEK_MODEL", "deepseek-chat"),
        fallback_model=_env_str("DEEPSEEK_FALLBACK_MODEL"),
        temperature=_env_float("LLM_TEMPERATURE", 0.3),
        request_timeout=_env_float("LLM_TIMEOUT", 60.0),
        max_retries=_env_int("LLM_MAX_RETRIES", 3),
        max_steps=_env_int("AGENT_MAX_STEPS", 8),
        max_input_chars=_env_int("AGENT_MAX_INPUT_CHARS", 8000),
        tool_timeout=_env_float("TOOL_TIMEOUT", 15.0),
        tool_max_concurrency=_env_int("TOOL_MAX_CONCURRENCY", 5),
        tool_max_output_chars=_env_int("TOOL_MAX_OUTPUT_CHARS", 4000),
        context_max_tokens=_env_int("CONTEXT_MAX_TOKENS", 6000),
        summary_trigger_tokens=_env_int("SUMMARY_TRIGGER_TOKENS", 1500),
        long_term_top_k=_env_int("LONG_TERM_TOP_K", 3),
        data_dir=Path(_env_str("AGENT_DATA_DIR", "data")),
        api_keys=_env_list("APP_API_KEYS"),
    ).validate()
