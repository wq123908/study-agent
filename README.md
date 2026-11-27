# study-agent 基础教学版

这个版本记录阶段 1–8，从零写出一个能在终端多轮对话、调用工具和保存历史的 ReAct Agent。代码基线对应 Git 标签 `v0.1.0-basic`（`4130eb8`）。

## 本版能力

- 通过 OpenAI 兼容接口调用模型。
- 运行 ReAct 循环，并按步数限制长时间循环。
- 调用时间和计算器工具，把工具返回交给模型生成答复。
- 用本地 JSON 保存对话历史，下次启动时恢复。

## 启动

在仓库根目录打开 PowerShell，使用 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe check_env.py
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在 `.env` 填写 `DEEPSEEK_API_KEY`，根据模型服务配置 `DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL`，然后运行下面的命令。

```powershell
.\.venv\Scripts\python.exe main.py
```

例如输入「现在几点」或「帮我算 25 × 4」体验工具调用，输入 `exit` 退出。

## 代码入口

- [main.py](main.py) 负责终端交互和组装组件。
- [agent/core.py](agent/core.py) 负责 ReAct 循环和工具调度。
- [agent/llm.py](agent/llm.py)、[agent/tools.py](agent/tools.py)、[agent/memory.py](agent/memory.py) 分别负责模型接入、工具与本地记忆。
