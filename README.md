# study-agent V1.0

V1.0 是从零手写的单机 Agent 框架归档，包含阶段 1–12 和 Web 对话工作台。代码基线为 `542fa2b`。终端和网页共用一个运行时，可以流式对话、并发调用工具，并在高危动作前等待人工批准。

## 本版能力

| 能力 | 已实现 |
| --- | --- |
| 模型与执行 | 异步流式 ReAct、模型重试与降级、步数与重复调用护栏。 |
| 工具与审批 | 声明式工具、参数校验、并发执行，以及人工批准或拒绝后恢复。 |
| 分层记忆 | L1 上下文窗口、L2 滚动摘要、L3 BM25 长期记忆。 |
| 交互与追踪 | CLI、FastAPI/SSE、Web 会话工作台和 JSONL Trace。 |
| 离线验证 | 52 项自动化测试和 12 条确定性回放用例。 |

## 本地运行

在仓库根目录打开 PowerShell，使用 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "openai>=1.40" "python-dotenv>=1.0" "pydantic>=2.7" "fastapi>=0.110" "uvicorn>=0.29" "pytest>=8" "pytest-asyncio>=0.23" httpx
```

离线测试和评测使用模拟模型，无需模型 API Key。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m eval.run_eval
```

首次运行对话时，复制 `.env.example` 到 `.env`，填写 `DEEPSEEK_API_KEY`。

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

启动 CLI。

```powershell
.\.venv\Scripts\python.exe main.py
```

启动 Web 后访问 [本地对话页](http://127.0.0.1:8000/)。

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 学习记录

- [阶段 1–8 · 单机 ReAct 基础](study_records/stage_01_08_review.md)
- [阶段 9 · 声明式工具和 Trace](study_records/stage_09.md)
- [阶段 10 · 流式模型和分层记忆](study_records/stage_10.md)
- [阶段 11 · 运行时、审批与 Web 服务](study_records/stage_11.md)
- [阶段 12 · 离线测试和回归评测](study_records/stage_12.md)
