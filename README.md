# study-agent（v0.2 企业级架构升级版）

从零手写的轻量级企业级 AI Agent 引擎 —— **不依赖 LangChain / AutoGen 等重型框架**，用不到 1,500 行高内聚的原生 Python 代码，完整实现**异步流式 ReAct 状态机、三级分层记忆（L1/L2/L3）、声明式安全工具网关、高危操作人工审批（HITL）、全链路 Trace 追踪与自动化回归评测**。

> 基础教学版（阶段 1～8）已保留在 Git 标签 `v0.1.0-basic`；详细架构设计见 [`enterprise_roadmap.md`](./enterprise_roadmap.md)。

---

## 核心特性（四大支柱）

| 支柱 | 核心能力 | 关键实现模块 |
| :--- | :--- | :--- |
| **1. 异步流式状态机与 HITL** | `AsyncOpenAI` 流式分片 `tool_calls` 聚合、指数退避重试 + 备用模型降级、单轮事务性提交、重复调用死循环护栏（`LoopGuard`）、高危工具 Checkpoint 挂起与审批恢复 | `agent/engine/core.py`<br>`agent/llm/provider.py`<br>`agent/state.py` |
| **2. 三级分层记忆与对齐裁剪** | **L1** 完整保存 `tool_calls`/`tool` 轨迹，按 Token 预算以“轮次”为原子单位逆序裁剪（绝不截断工具配对避免 API 400）；**L2** 滑出窗口自动触发滚动摘要；**L3** 跨会话用户事实库 + BM25 检索注入 | `agent/memory/window.py`<br>`agent/memory/summarizer.py`<br>`agent/memory/long_term.py` |
| **3. 声明式工具网关与安全沙箱** | `@registry.tool()` 从类型注解与 docstring 自动生成 OpenAI JSON Schema 与 Pydantic 严格校验模型、错误回填引导模型自我纠错、`asyncio.gather` 并发限流与超时熔断、AST 白名单安全计算器 | `agent/tools/base.py`<br>`agent/tools/executor.py`<br>`agent/tools/builtin.py` |
| **4. 全链路可观测与自动化评测** | 基于 `contextvars` 的 `Trace -> Span` 树（记录 TTFT、Token 用量、每步耗时）导出 JSONL + 终端瀑布图查看器；12 条黄金基准用例覆盖轨迹准确率、事实忠实度与故障自愈率 | `agent/observability/`<br>`eval/run_eval.py` |

---

## 目录结构

```text
study-agent/
├── app/                        # FastAPI Web 服务层（SSE 流式网关 + HITL 审批接口）
│   ├── main.py
│   └── schemas.py
├── agent/
│   ├── config.py               # 强类型环境变量配置与启动校验
│   ├── message.py              # 完整支持 tool_calls / reasoning / metadata 的消息模型
│   ├── state.py                # 会话状态与 HITL Checkpoint 模型
│   ├── factory.py              # Agent 组装工厂
│   ├── engine/
│   │   ├── core.py             # 异步流式 ReAct 状态机引擎
│   │   ├── events.py           # 统一事件流协议（CLI 与 SSE 共用）
│   │   └── guardrails.py       # 死循环检测与输入校验护栏
│   ├── llm/
│   │   ├── provider.py         # AsyncLLM：流式聚合、指数退避重试、主备模型降级
│   │   └── token_counter.py    # Token 预算估算器（tiktoken / 中英启发式双模式）
│   ├── memory/
│   │   ├── manager.py          # L1/L2/L3 统一记忆门面
│   │   ├── store.py            # 会话存储接口与原子 JSON 文件实现
│   │   ├── window.py           # 轮次对齐的 Token 窗口裁剪器
│   │   ├── summarizer.py       # L2 滚动摘要压缩器
│   │   └── long_term.py        # L3 跨会话事实库（BM25 检索）
│   ├── tools/
│   │   ├── base.py             # @registry.tool 声明式注册表与风险分级
│   │   ├── executor.py         # 异步并发执行器（Pydantic 校验、超时隔离、故障注入）
│   │   └── builtin.py          # 内置工具：AST 安全计算器、时间、长期记忆、沙箱写文件
│   └── observability/
│       ├── tracer.py           # Trace / Span 全链路追踪器与 JSONL 导出
│       ├── logger.py           # 含 trace_id 的结构化日志
│       └── view.py             # 终端 Trace 瀑布图查看器
├── eval/
│   ├── datasets/golden_cases.jsonl
│   └── run_eval.py             # 自动化回归评测流水线
├── tests/                      # 51 项单元与端到端测试（全离线可跑）
├── main.py                     # 交互式流式 CLI 入口
└── enterprise_roadmap.md       # 企业级演化路径与架构设计白皮书
```

---

## 快速开始

### 1. 安装依赖与配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入真实的 DEEPSEEK_API_KEY
pip install -r requirements.txt
python check_env.py
```

### 2. 运行交互式流式 CLI

```bash
python main.py
```

CLI 内置命令：
- `/state`：查看当前会话消息数、状态与 L2 滚动摘要
- `/trace`：在终端打印最近一次推理的 Trace 瀑布图
- `/session <id>`：切换多会话
- `/reset`：清空当前会话

### 3. 启动 FastAPI + SSE 流式服务

```bash
uvicorn app.main:app --reload --port 8000
```

调用 SSE 流式对话接口：

```bash
curl -N -X POST http://127.0.0.1:8000/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"session_id": "demo", "message": "现在几点了？顺便算一下 1234 * 5678"}'
```

当触发 `HIGH_RISK` 工具（如 `write_workspace_file`）时，流会收到 `event: approval_required` 并保存 Checkpoint，可通过审批接口恢复执行：

```bash
curl -X POST http://127.0.0.1:8000/v1/chat/approve \
  -H "Content-Type: application/json" \
  -d '{"session_id": "demo", "approve": true, "stream": false}'
```

### 4. 查看 Trace 瀑布图

```bash
python -m agent.observability.view --list 10
python -m agent.observability.view
```

### 5. 运行测试与自动化回归评测

```bash
pytest -q
python -m eval.run_eval          # 离线确定性回放评测（CI 门禁）
python -m eval.run_eval --live   # 调用真实大模型端到端评测
```
