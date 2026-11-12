"""环境与企业级模块自检脚本。"""
from __future__ import annotations

import sys
from pathlib import Path

import dotenv
import fastapi
import openai
import pydantic

from agent import __version__
from agent.config import load_config
from agent.tools import default_registry


def main() -> int:
    cfg = load_config(require_api_key=False)
    reg = default_registry()
    print("=" * 60)
    print("study-agent 版本 :", __version__)
    print("Python 版本      :", sys.version.split()[0])
    print("解释器路径       :", sys.executable)
    print("openai 版本      :", openai.__version__)
    print("pydantic 版本    :", pydantic.__version__)
    print("fastapi 版本     :", fastapi.__version__)
    print("dotenv 路径      :", dotenv.__file__)
    print("当前工作目录     :", Path.cwd())
    print("是否在 venv      :", sys.prefix != sys.base_prefix)
    print("已注册内置工具   :", ", ".join(reg.names()))
    print("数据目录         :", cfg.data_dir)
    print("=" * 60)

    if sys.prefix == sys.base_prefix:
        print("警告：当前不在虚拟环境中，请先激活 .venv")
    else:
        print("环境自检通过！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
