# 阶段 11 学习记录：异步流式 ReAct 状态机、HITL 人工审批与 FastAPI SSE

- **目标**：构建统一事件流协议与防死循环护栏；将同步阻塞的 `agent/core.py` 演进为支持单会话互斥、工作副本原子提交、高危工具挂起审批（Human-in-the-Loop）与恢复续关的异步状态机引擎；并分别对外提供异步流式 CLI 与 FastAPI + SSE Web 服务网关。
- **阶段状态**：✅ 已完成（**11.1 ～ 11.4** 全部验收通过，异步流式状态机、HITL 审批、CLI 与 FastAPI SSE 网关全面闭环）

---

## 环节进度

| 环节 | 主题 | 状态 | 提交 Hash |
| :---: | :--- | :---: | :--- |
| 11.1 | 统一事件流协议与护栏 | ✅ 已完成 | `23dcf74` |
| 11.2 | 异步状态机引擎与 HITL 检查点 | ✅ 已完成 | `364face` |
| 11.3 | 异步流式 CLI 升级 | ✅ 已完成 | `18e472e` |
| 11.4 | FastAPI + SSE Web 网关 | ✅ 已完成 | `study(stage-11.4)` |

---

## 11.1 统一事件流协议与护栏
- **状态**：✅ 已完成（一次性零失误验收通过，耗时约 14 分钟：`2026-11-26 16:06 ~ 16:20`）
- **改动文件**：`agent/engine/events.py`、`agent/engine/guardrails.py`、`agent/engine/__init__.py`
- **学习知识点详解**：
  1. **统一事件流协议（`agent/engine/events.py`）**：
     - 定义 10 类引擎生命周期事件常量（`run_start`、`step_start`、`thinking_delta`、`content_delta`、`tool_call_start`、`tool_call_result`、`approval_required`、`approval_resolved`、`done`、`error`）；
     - `AgentEvent` 同时提供 `.to_dict()`（供 CLI 与非流式接口消费）和 `.to_sse()`（按标准 `event: <type>\ndata: <json>\n\n` 双换行帧格式推送给浏览器），配合 `default=str` 兜底防止非 JSON 原生对象报错；`error_event()` 统一错误结构。
  2. **防死循环与输入护栏（`agent/engine/guardrails.py`）**：
     - `tool_signature()` 用 `json.loads` + `json.dumps(..., sort_keys=True)` 消除参数键序与空格差异，用 `\x00` 零字节隔离工具名与参数防拼接撞车，SHA-256 取 32 位哈希，残缺 JSON 优雅回退 `.strip()`；
     - `LoopGuard` 支持通过 `seen` 从 HITL 检查点还原已见签名，首次重复返回重复 `id` 注入纠偏，累计违规达到 `max_violations` 触发 `tripped` 熔断；
     - `validate_user_input()` 拦截空白串与超长输入。
- **验收命令与结果**：
  - `1_sse_ok: True | err_type: error invalid_input`
  - `2_same_sig: True | len: 32`
  - `3_loop_guard: set() {'2'} False -> {'3'} True`
  - `4_input: 输入不能为空 | 输入过长（11 字符），上限 10 字符 | None`
- **掌握情况与踩坑记录**：三个文件一次性零笔误全绿通过！下一步进入核心引擎 **11.2 异步状态机引擎与 HITL 检查点**。

## 11.2 异步状态机引擎与 HITL 检查点
- **状态**：✅ 已完成（全模块零报错验收通过，耗时约 87 分钟：`2026-11-26 16:20 ~ 17:47`，已退役旧版同步 `agent/core.py`）
- **改动文件**：`agent/engine/core.py`、`agent/factory.py`、`agent/engine/__init__.py`、`agent/__init__.py`（并移除旧 `agent/core.py`）
- **学习知识点详解**：
  1. **底层原子零件与汇总漏斗（`agent/engine/core.py`）**：
     - `_call_llm()` 调 `MemoryManager.build_context()` 组装上下文，按需无污染附加 `extra_notice`，实时将 `LLMEvent` 翻译为对外 `AgentEvent`（`THINKING_DELTA` / `CONTENT_DELTA`）并在 `message_complete` 统一累计 `current_trace().add_usage()`；
     - `_execute_calls()` 支持同一步内 `running`（并发执行）/ `blocked`（重复护栏拦截）/ `rejected`（人工拒绝）三路分流，并严格按原 `calls` 顺序回填 `role="tool"` 回执维护协议合法性；
     - `collect()` 将异步事件流汇总为标准结构化字典，一套流式引擎同时服务非流式接口、单测与评测。
  2. **异步 ReAct 状态机与 HITL 审批闭环（`agent/engine/core.py`）**：
     - `_guarded_run()` 统一收口单会话互斥（`self._running` + 冲突时 `body.aclose()` 防泄漏）、Trace 生命周期与全异常转 `error_event`；
     - `_chat_body()` 拦截 `WAITING_APPROVAL` 挂起会话的新插队消息，并在内存 `working` 工作副本上推进，确保单轮异常零脏数据落盘；
     - `_run_loop()` 遇 `HIGH_RISK` 工具立刻踩刹车存 `PendingApproval`（含 `step`、`tool_call_ids`、`blocked_ids`、`seen_signatures`）进入挂起；达 `max_steps` 或 `LoopGuard.tripped` 熔断时进入 `finalize` 阶段，`tools=None` 缴械强制总结并清空防御性 `tool_calls`；
     - `_resume_body()` 支持整批 `approve` 与逐项 `decisions` 覆盖，还原 `LoopGuard` 执行工具后**立刻 `commit` 落盘防重放**，再从 `pending.step + 1` 续关。
  3. **依赖注入总装工厂（`agent/factory.py`）**：
     - `build_agent(config, ...)` 通过命名关键字参数支持把 `llm` / `registry` / `store` / `long_term` / `exporters` / `fault_injector` 任意替换为测试替身，使用 `is not None` 精确区分“未传”与显式传空列表 `exporters=[]`。
- **验收命令与结果**：
  - 原子零件验收：`1_call_llm: ['thinking_delta', 'content_delta'] | final: 答案是84 | tokens: {'total_tokens': 15} | notice_ok: True`、`2_exec_statuses: ['running', 'blocked', 'rejected']`、`3_exec_results: [('c1', '84'), ('c2', '[护栏] 你'), ('c3', '[已拒绝] ')]`、`4_collect: done tr_99 冷链核验完毕 2`；
  - 4 大核心场景实战验收：`1_hitl_approve: waiting_approval | before: False | block_new: approval_pending | after: done`、`2_hitl_reject: done | file_exists: False | err_type: rejected`、`3_loop_finalize: done | truncated: True`、`4_atomic_rollback: error llm_error | saved_msgs: 0`；
  - `factory.py` 总装配与退役验收：全部通过，`agent.__version__ == "0.2.0"`，旧 `agent/core.py` 已移除。
- **掌握情况与踩坑记录**：718 行核心异步状态机引擎一次性手敲零 Bug 通关！顺带积累了 Windows PowerShell 5.1 用 `py -c` 传空双引号 `""` 被 Win32 解析器吞引号的排错经验（改用 `$OutputEncoding = [Text.Encoding]::UTF8; @' ... '@ | py -` 完美免疫）。下一步进入 **11.3 异步流式 CLI 升级（`main.py`）**。

## 11.3 异步流式 CLI 升级
- **状态**：✅ 已完成（一次性零失误验收通过，耗时约 4 分钟：`2026-11-26 17:47 ~ 17:51`）
- **改动文件**：`main.py`
- **学习知识点详解**：
  1. **非阻塞异步输入（`loop.run_in_executor(None, input, ...)`）**：避免同步 `input()` 阻塞 `asyncio` 事件循环，确保用户思考打字期间后台 L2 滚动摘要协程能正常并发运行；退出时在 `finally` 中调用 `await agent.memory.wait_background()` 优雅停机。
  2. **流式事件渲染与递归 HITL 审批（`_consume` / `_render_event` / `_handle_approval`）**：`flush=True` 实时逐字输出思考与回答、渲染工具耗时卡片与完成账单；遇到 `APPROVAL_REQUIRED` 挂起后终端询问 `y/n` 并递归消费 `agent.resume()` 事件流，天然支持连续多轮高危审批。
  3. **会话斜杠命令与旧数据无损迁移**：实现 `/session <id>`、`/state`、`/trace`（直接调 `render_waterfall` 输出终端 ASCII 瀑布图）、`/reset` 与 `_migrate_legacy_memory()` 自动迁移阶段 4 遗留的 `memory.json`。
- **验收命令与结果**：
  - 离线模拟完整流程验收通过：实时输出思考/工具/回答/完成栏，`/session cold_01`、`/state`、`/trace`（成功渲染 `step-1`/`memory:build_context`/`tool:calculator`/`step-2` 瀑布图）与 `/reset` 全部正常，`OK_NEW_SID: cold_01 | AFTER_RESET_MSGS: 0`。
- **掌握情况与踩坑记录**：290 行新版 `main.py` 一把零失误通过！下一步进入阶段 11 收官战 **11.4 FastAPI + SSE Web 网关**。

## 11.4 FastAPI + SSE Web 网关
- **状态**：✅ 已完成（全接口 `TestClient` 联调零失误通过，耗时约 4 分钟：`2026-11-26 17:51 ~ 17:55`，阶段 11 圆满收官）
- **改动文件**：`app/__init__.py`、`app/schemas.py`、`app/main.py`
- **学习知识点详解**：
  1. **网关入口 Pydantic 强校验（`app/schemas.py`）**：`ChatRequest` / `ApproveRequest` 在 HTTP 边界用正则 `^[A-Za-z0-9_\-]{1,64}$` 拦截非法 `session_id`、限制消息长度；`ChatResponse` 统一非流式返回契约。
  2. **生产级 SSE 推送与 Nginx 防缓冲（`app/main.py`）**：`_sse_stream()` 封装 `StreamingResponse(..., media_type="text/event-stream")` 并附带 `X-Accel-Buffering: no`、`Cache-Control: no-cache`、`Connection: keep-alive`，杜绝反向代理攒包卡顿。
  3. **应用工厂、优雅停机与双通道鉴权**：`create_app(agent=None, config=None)` 支持生产 `lifespan` 自动装配与关机 `wait_background()`，同时允许测试直接注入内存假引擎；`verify_api_key` 兼容 `X-API-Key` 与 `Authorization: Bearer` 两种令牌且不拦 `/healthz`。
  4. **完整 6 端点契约**：`GET /healthz`、`POST /v1/chat/stream`、`POST /v1/chat`、`POST /v1/chat/approve`（支持 `stream=True/False` 双模式）、`GET/DELETE /v1/sessions/{session_id}`。
- **验收命令与结果**：
  - `TestClient` 全链路自动化验收全部通过：
    - `1_health: ok | tools_count: 5 | unauth_code: 401`
    - `2_sse: True | no_buf: no | has_approval_ev: True`
    - `3_approve: done | content: 报告已写入完成 | file: 冷链审核通过`
    - `4_session: 4 | deleted: True`
  - 结构化日志成功自动注入 `trace_id`（`8d0e6f5ccc71`）。
- **掌握情况与踩坑记录**：三个文件零笔误一把过！阶段 11 全线通关，下一步进入通用底层框架的最后一关 **阶段 12：自动化测试套件与回归评测流水线**。
