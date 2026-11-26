# 完整课程大纲与知识点总表（阶段 1 ～ 阶段 12）

> 阶段 1～8 对齐 [`../.trae/skills/agent-build-coach/SKILL.md`](../.trae/skills/agent-build-coach/SKILL.md)；
> 阶段 9～12 由 [`../enterprise_roadmap.md`](../enterprise_roadmap.md) 细化拆解为 **14 个可独立动手、可独立验收的小环节**。

---

## 第一部分：基础教学篇（阶段 1 ～ 8，已完成）

| 阶段 | 主题 | 核心知识点 | 交付物 | 状态 |
| :---: | :--- | :--- | :--- | :---: |
| 1 | 环境准备 | Python `venv` 隔离、依赖管理、`sys.prefix` 校验 | `requirements.txt`、`check_env.py` | ✅ |
| 2 | Agent 骨架 | `Message` 数据结构、角色交替、最小对话闭环 | `agent/message.py`、`agent/core.py`、`check_step2.py` | ✅ |
| 3 | 模型对接 | `.env` 配置加载、`OpenAI` 兼容客户端封装 | `agent/config.py`、`agent/llm.py`、`check_step3.py` | ✅ |
| 4 | 记忆模块 | JSON 文件持久化、冷启动加载与单轮保存 | `agent/memory.py`、`check_step4.py` | ✅ |
| 5 | 工具调用 | Function Calling JSON Schema、`TOOL_MAP` 路由 | `agent/tools.py`、`check_step5.py` | ✅ |
| 6 | 多轮对话 | CLI 交互循环、输入清洗与 `KeyboardInterrupt` 处理 | `main.py` | ✅ |
| 7 | 调度流程 | ReAct 循环（`_think`）、`MAX_STEP` 防死循环兜底 | `agent/core.py` | ✅ |
| 8 | 调试健壮性 | `logging` 分级日志、顶层异常兜底、`trim(max_count)` 窗口裁剪 | `agent/memory.py`、`main.py` | ✅ |

---

## 第二部分：企业级演进篇（阶段 9 ～ 12，待手敲）

### 阶段 9：基线修复、声明式安全工具层与全链路追踪底座

| 环节 | 主题 | 核心知识点 | 涉及文件 | 验收标准 | 状态 |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **9.1** | 基线止血与强类型配置 | 空指针修复（`os.getenv` 判空）、`Config.validate()` 启动校验、`ConfigError`、清理死代码与 `.gitignore` | `agent/config.py`<br>`agent/llm.py`<br>`.env.example`<br>`.gitignore` | 未配置 `.env` 时抛出可读的 `ConfigError` 而非 `AttributeError`；`check_env.py` 正常输出配置 | ✅ |
| **9.2** | 完整消息协议模型 | `ToolCallItem`、`tool_call_id`、`reasoning_content`、`to_dict()`（发 API）与 `to_record()`（落盘）分离、兼容旧 `memory.json` | `agent/message.py` | 含 `tool_calls` 与 `tool` 的消息可完整序列化/反序列化，且能读取阶段 4 旧版 JSON | ✅ |
| **9.3** | AST 安全计算器 | 用 Python `ast.parse` 白名单语法树替代危险的 `eval()`，限制表达式长度、指数与数值范围 | `agent/tools/builtin.py` | `12*(3+4)` 返回 `"84"`；`__import__('os').system('whoami')`、`9**99999` 等被拦截返回安全提示 | ✅ |
| **9.4** | 声明式工具注册与并发执行器 | `@registry.tool` + `inspect` + `pydantic.create_model` 自动推导 Schema、`ToolContext` 注入、`RiskLevel` 分级、`asyncio.Semaphore` + `wait_for` + `gather` 并发、校验错误回填自愈 | `agent/tools/__init__.py`<br>`agent/tools/base.py`<br>`agent/tools/executor.py`<br>`agent/tools/builtin.py` | 自动导出 OpenAI Schema（不含 `ctx`）；故意传错参数名返回 `[参数校验失败]`；4 个 0.3s 异步工具并发总耗时 < 0.9s；沙箱写文件拒绝 `../` 越界 | ✅ |
| **9.5** | 全链路 Trace 与结构化日志 | `contextvars` 透传 `Trace` / `Span` 树、TTFT 与 `usage` 统计、JSONL 导出、`TraceContextFilter`、终端 ASCII 瀑布图 | `agent/observability/__init__.py`<br>`agent/observability/tracer.py`<br>`agent/observability/logger.py`<br>`agent/observability/view.py` | 跑一次嵌套 `span` 后写出 `.jsonl`，运行 `python -m agent.observability.view` 在终端打印树状瀑布图 | ✅ |

---

### 阶段 10：异步流式 LLM 与 L1 / L2 / L3 分层记忆

| 环节 | 主题 | 核心知识点 | 涉及文件 | 验收标准 | 状态 |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **10.1** | AsyncLLM 流式聚合与重试降级 | `AsyncOpenAI` 流式读取、按 `tc.index` 拼接分片 `tool_calls`、支持 `reasoning_content`、未吐字前指数退避重试 + `fallback_model` 降级 | `agent/llm/__init__.py`<br>`agent/llm/provider.py` | 用模拟分片流可拼出完整工具调用；主模型超时重试耗尽后自动切换备用模型成功 | ✅ |
| **10.2** | L1 Token 预算窗口与原子存储 | Token 估算（`tiktoken` + 启发式降级）、按 `USER` 轮次边界逆序裁剪、`sanitize()` 清除孤立 `tool` / 补全缺失结果、`mkstemp + os.replace` 原子写盘与 `session_id` 防穿越 | `agent/llm/token_counter.py`<br>`agent/state.py`<br>`agent/memory/store.py`<br>`agent/memory/window.py` | 30 轮含工具历史裁剪后第一条必为 `user` 且 `tool_calls` 100% 配对；`../etc/passwd` 被 `InvalidSessionId` 拦截 | ✅ |
| **10.3** | L2 异步滚动摘要 | 滑出窗口且未摘要消息超阈值时后台生成摘要、注入 System Prompt、`created_at` + `summarized_upto` 乐观锁防并发覆盖 | `agent/memory/summarizer.py`<br>`agent/memory/manager.py` | 历史超出窗口后自动触发摘要并注入上下文；旧快照再次 `commit` 不会覆盖新摘要 | ✅ |
| **10.4** | L3 跨会话长期记忆（BM25） | 按 `user_id` 隔离的事实库、中文单字+二元组与英文分词、BM25 相关性排序、`remember_fact` / `recall_facts` 工具集成 | `agent/memory/long_term.py`<br>`agent/tools/builtin.py` | 会话 A 存入用户偏好，新建会话 B 提问相关词能检索出该事实；不同 `user_id` 互相隔离 | ✅ |

---

### 阶段 11：流式 ReAct 状态机、HITL 人工审批与 FastAPI SSE 服务化

| 环节 | 主题 | 核心知识点 | 涉及文件 | 验收标准 | 状态 |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **11.1** | 统一事件流协议与护栏 | `AgentEvent`（`.to_dict()` / `.to_sse()`）、参数规范化哈希 `LoopGuard` 防死循环、输入合法性校验 | `agent/engine/__init__.py`<br>`agent/engine/events.py`<br>`agent/engine/guardrails.py` | 同参工具第二次调用被拦截并注入纠偏提示，达到上限触发熔断 | ✅ |
| **11.2** | 异步状态机引擎与 HITL 检查点 | 单会话互斥、工作副本原子提交、触发 `HIGH_RISK` 保存 `PendingApproval` 挂起、`resume()` 批准/拒绝恢复、`max_steps` 无工具强制收尾 | `agent/engine/core.py`<br>`agent/factory.py` | 调用 `write_workspace_file` 时返回 `waiting_approval` 且未写磁盘；批准后执行写盘并完成对话；拒绝则回填拒绝通知 | ✅ |
| **11.3** | 异步流式 CLI 升级 | 消费事件流实时打印思考/回答/工具状态、终端确认审批、`/session` `/state` `/trace` `/reset` 命令与旧 `memory.json` 迁移 | `main.py` | 启动 `python main.py` 可看到流式打字效果、工具卡片与终端审批交互，`/trace` 可看最近一次瀑布图 | ⬜ |
| **11.4** | FastAPI + SSE Web 网关 | `StreamingResponse` SSE 推送、`/v1/chat/stream`、`/v1/chat`、`/v1/chat/approve`、会话管理与 API Key 鉴权 | `app/__init__.py`<br>`app/schemas.py`<br>`app/main.py` | `uvicorn app.main:app` 启动后，`curl -N` 可实时收到 `content_delta` 与 `approval_required` 事件并通过 `/v1/chat/approve` 恢复 | ⬜ |

---

### 阶段 12：自动化测试套件与回归评测流水线

| 环节 | 主题 | 核心知识点 | 涉及文件 | 验收标准 | 状态 |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **12.1** | 离线单元测试与端到端测试 | `ScriptedLLM` 假大脑、`TestClient` 接口测试、覆盖工具/记忆/状态机/重试降级（避开 `httpx2` 拼写坑） | `tests/conftest.py`<br>`tests/test_*.py`<br>`pyproject.toml` | 运行 `pytest -q` 全部测试离线通过 | ⬜ |
| **12.2** | 黄金评测集与门禁流水线 | `ReplayLLM` 确定性回放 + `--live` 实测、轨迹召回率/非法工具率/忠实度/`FaultInjector` 混沌自愈门禁报表 | `eval/__init__.py`<br>`eval/datasets/golden_cases.jsonl`<br>`eval/run_eval.py` | 运行 `python -m eval.run_eval` 输出四项指标且全部达标 `PASSED` | ⬜ |
