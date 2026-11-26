# 阶段 11 学习记录：异步流式 ReAct 状态机、HITL 人工审批与 FastAPI SSE

- **目标**：构建统一事件流协议与防死循环护栏；将同步阻塞的 `agent/core.py` 演进为支持单会话互斥、工作副本原子提交、高危工具挂起审批（Human-in-the-Loop）与恢复续关的异步状态机引擎；并分别对外提供异步流式 CLI 与 FastAPI + SSE Web 服务网关。
- **阶段状态**：⏳ 进行中（已完成 **11.1**、**11.2**，准备开始 **11.3**）

---

## 环节进度

| 环节 | 主题 | 状态 | 提交 Hash |
| :---: | :--- | :---: | :--- |
| 11.1 | 统一事件流协议与护栏 | ✅ 已完成 | `23dcf74` |
| 11.2 | 异步状态机引擎与 HITL 检查点 | ✅ 已完成 | `study(stage-11.2)` |
| 11.3 | 异步流式 CLI 升级 | ⏳ 待开始 | - |
| 11.4 | FastAPI + SSE Web 网关 | ⬜ 待开始 | - |

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
- **状态**：⬜ 待开始
- **预习知识点导览**：
  - 异步消费 `AgentEvent` 实时打印思考折叠/流式吐字/工具卡片与终端 HITL 审批确认；
  - 支持 `/session` `/state` `/trace` `/reset` 命令与旧 `memory.json` 迁移。
- **改动文件**：`main.py`（待手敲）

## 11.4 FastAPI + SSE Web 网关
- **状态**：⬜ 待开始
- **预习知识点导览**：
  - `StreamingResponse` SSE 实时推送、`/v1/chat/stream`、`/v1/chat`、`/v1/chat/approve`、会话管理接口与 API Key 鉴权中间件。
- **改动文件**：`app/__init__.py`、`app/schemas.py`、`app/main.py`（待手敲）
