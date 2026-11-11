import sys
from pathlib import Path
import dotenv
import openai


print("=" * 50)
print("Python 版本 :", sys.version.split()[0])
print("解释器路径  :", sys.executable)
print("openai 版本 :", openai.__version__)
print("dotenv 路径 :", dotenv.__file__)
print("当前工作目录:", Path.cwd())
print("是否在 venv :", sys.prefix != sys.base_prefix)
print("=" * 50)

if sys.prefix == sys.base_prefix:
    print("警告：当前不在虚拟环境中，请先激活 .venv")
else:
    print("环境自检通过，可以进入阶段 2")