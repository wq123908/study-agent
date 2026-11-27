# study-agent V1.0

从零手写的 Python 单机 Agent 框架，归档阶段 1–12 与 Web 对话工作台。代码基线为 `542fa2b`。CLI、FastAPI 和离线评测共用一个异步 ReAct 内核，包含流式模型输出、声明式工具、L1/L2/L3 记忆、人工审批和请求级追踪。

**本版验证覆盖 52 项自动化测试和 12 条离线回放用例。** 可用模拟模型复现工具调用、审批、故障注入与回复校验。

## 本版能力

### 流式 ReAct 与模型容错

- 使用异步 OpenAI 兼容客户端。把响应增量聚合为消息，按工具调用索引拼接分片的函数名和 JSON 参数，再交给执行循环。
- CLI 与 Web 共用 `AgentEvent`。一轮请求可产生模型增量、执行步、工具调用、审批、结果和错误事件，FastAPI 将事件编码成 SSE。
- 对可重试的模型异常采用指数退避与抖动，配置了备用模型时可切换。响应已向调用端输出后，运行时返回流式错误并结束本轮。
- 工具请求进入 ReAct 循环。输入长度、执行步数和同轮重复调用有各自的检查，达到停止条件时会禁用工具进行最终收尾。

[流式模型客户端](agent/llm/provider.py) · [ReAct 执行循环](agent/engine/core.py) · [事件协议](agent/engine/events.py)

### 工具声明、并发和执行护栏

- 通过装饰器注册 Python 函数，从类型标注、默认值与字段描述生成 OpenAI 工具 Schema，调用前用 Pydantic 校验 JSON 对象，拒绝额外字段。
- `ToolContext` 由执行器注入，携带会话、用户标识、工作目录和记忆依赖。它独立于模型可填写的工具参数。
- 同一步的多个工具可以并发执行。执行器统一处理并发数量、等待超时、错误类型和长结果截断，按调用顺序返回结果。
- 内置时间、AST 白名单计算器、记忆写入与检索，以及需要审批的工作目录写文件工具。

[工具注册](agent/tools/base.py) · [并发执行器](agent/tools/executor.py) · [内置工具](agent/tools/builtin.py) · [工具测试](tests/test_tools.py)

### 人工审批与会话状态

模型提出高危工具调用时，运行时先把待执行调用和当前消息保存成会话检查点，再发出 `approval_required`。后续请求能读取待审批状态。批准后执行对应操作，拒绝后把拒绝结果回传模型，两条路径均可从该会话继续生成答复。内置写文件工具会校验文件名和解析后的工作目录路径。

本地会话 JSON 通过临时文件和原子替换写入。同一运行中的完整消息链保留在会话历史里，可通过 Web 重新加载已有会话。

[审批与状态恢复](agent/engine/core.py) · [会话存储](agent/memory/store.py) · [HTTP 审批测试](tests/test_api.py)

### 分层上下文与长期记忆

| 层级 | 职责 | 实现 |
| --- | --- | --- |
| L1 · 近期对话 | 构造当前模型请求的历史窗口 | 按 Token 预算从最近一轮选取完整轮次，保留最新一轮，并处理缺失或孤立的工具返回。 [窗口裁剪](agent/memory/window.py) |
| L2 · 滚动摘要 | 保留滑出窗口的早期对话信息 | 历史达到触发条件后后台生成增量摘要，保存摘要及其覆盖的消息位置。 [上下文组装](agent/memory/manager.py) |
| L3 · 长期事实 | 跨会话查询同一用户标识下的偏好和事实 | 本地保存事实，用 BM25 检索，将命中的信息放入模型上下文。 [长期记忆](agent/memory/long_term.py) |

### Trace 与可替换组件

一次请求用 Trace 关联推理步骤、模型请求、工具调用和上下文组装。模型 Span 可记录模型、轮次、首个输出增量耗时、Token 用量与结束原因。默认 Trace 导出为 JSONL，CLI 的 `/trace` 可查看最近请求的瀑布图。

`build_agent()` 统一组装模型、工具、会话存储、长期记忆和 Trace 导出器。离线测试使用可控的模型实现和内存存储复现关键执行路径。

[Trace 导出与 Span](agent/observability/tracer.py) · [组装工厂](agent/factory.py) · [测试替身](tests/conftest.py)

## 在工作台演示

1. 在 Web 或 CLI 输入「帮我算 25 × 4」，观察计算器调用、工具结果和流式回复。
2. 输入「把今日巡检正常写入 inspection-demo.md」。模型选择写文件工具后，运行时先展示待审批操作。批准时检查默认的 `data/workspace/inspection-demo.md`，也可以另用一个文件名验证拒绝流程。
3. 在 CLI 输入 `/trace` 查看最近请求的 Trace。Web 支持切换已保存的会话，查看历史消息及工具调用。

模型行为取决于配置的模型服务。可使用下面的离线回放命令稳定复现工具使用和审批路径。

## 离线验证

| 测试范围 | 可验证行为 |
| --- | --- |
| 模型与消息协议 | 流式分片组装、主备模型切换、Token 与 Trace。 [模型测试](tests/test_llm.py) |
| 执行器与状态 | 工具入参纠正、重复调用限制、步数收尾、审批批准与拒绝。 [执行循环测试](tests/test_engine.py) |
| 工具与记忆 | 批量并发、超时分类、工作目录路径校验、轮次裁剪、摘要、BM25。 [工具测试](tests/test_tools.py) · [记忆测试](tests/test_memory.py) |
| Web 与接口 | Web 页面、会话列表、SSE 流式接口和 HTTP 审批。 [API 测试](tests/test_api.py) |

12 条离线回放用例通过 `ReplayLLM` 固定模型响应，运行真实工具与引擎，并覆盖一次性工具故障注入。评测检查预期工具是否出现、是否调用未注册工具，以及回复能否命中预期事实和工具结果。当前离线用例已通过评测门禁。

[回放样例](eval/datasets/golden_cases.jsonl) · [评测程序](eval/run_eval.py)

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
