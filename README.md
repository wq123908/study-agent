# study-agent V1.0

## 项目介绍

基于 Python 的单机 Agent 框架，提供流式对话、工具执行、分层记忆、人工审批和运行追踪。CLI、FastAPI 和离线评测共用异步 ReAct 运行时，Web 工作台通过 SSE 展示回复、工具状态和审批记录。

| 能力 | 实现及入口 |
| --- | --- |
| 异步运行与事件流 | 按次执行模型请求和工具调用，统一发布回复增量、执行步骤、工具、审批与结果事件。对输入长度、步骤数和重复工具调用设置约束。 [运行时](agent/engine/core.py) · [事件协议](agent/engine/events.py) |
| 模型适配与容错 | 聚合 OpenAI 兼容接口返回的文本和工具调用分片。在输出首个分片前，对符合条件的异常执行退避重试，并按配置切换备用模型。 [模型客户端](agent/llm/provider.py) |
| 工具声明与执行 | 根据 Python 类型标注生成工具 Schema 并通过 Pydantic 校验入参。运行时注入 `ToolContext`，限制并发、处理超时并按调用顺序返回结果。 [工具注册](agent/tools/base.py) · [执行器](agent/tools/executor.py) |
| 分层记忆 | L1 按 Token 预算保留近期完整轮次，L2 后台维护滚动摘要，L3 按用户标识从本地事实库做 BM25 检索。 [窗口裁剪](agent/memory/window.py) · [上下文组装](agent/memory/manager.py) · [长期记忆](agent/memory/long_term.py) |
| 审批与会话持久化 | 高风险工具在执行前保存会话检查点。批准则恢复执行，拒绝则向模型返回拒绝结果。会话 JSON 通过临时文件和原子替换保存。 [审批流程](agent/engine/core.py) · [会话存储](agent/memory/store.py) |
| 运行追踪与接口 | JSONL Trace 关联模型请求、工具步骤、上下文、耗时和可用的 Token 用量。CLI 可查看 Trace，Web 支持查看历史会话、流式回复和审批。 [追踪导出](agent/observability/tracer.py) · [FastAPI 接口](app/main.py) · [Web 工作台](app/static/index.html) |
| 组件复用 | 统一组装入口支持替换模型客户端、工具注册表、会话存储和 Trace 导出器，为离线验证提供注入点。 [组件组装](agent/factory.py) |

## 项目进度

V1.0 已完成阶段 1–12 和 Web 工作台，代码基线为 `542fa2b`。已验证 **52 项自动化测试和 12 条确定性离线回放**，覆盖模型降级、工具参数校验、并发执行、记忆、审批和 HTTP 接口。离线评测由模拟模型固定响应，运行时与内置工具实际执行。 [自动化测试](tests/) · [回放用例](eval/datasets/golden_cases.jsonl) · [评测程序](eval/run_eval.py)

## 运行说明

使用 Python 3.11 或更高版本，在项目根目录执行以下 PowerShell 命令。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "openai>=1.40" "python-dotenv>=1.0" "pydantic>=2.7" "fastapi>=0.110" "uvicorn>=0.29" "pytest>=8" "pytest-asyncio>=0.23" httpx
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在 `.env` 中填写 `DEEPSEEK_API_KEY`。CLI 使用 `.\.venv\Scripts\python.exe main.py`，Web 使用 `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`，启动后访问 [本地工作台](http://127.0.0.1:8000/)。

离线验证使用模拟模型，无需配置密钥。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m eval.run_eval
```
