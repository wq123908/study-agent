# 阶段 11 学习记录：异步流式 ReAct 状态机、HITL 人工审批与 FastAPI SSE

- **目标**：构建统一事件流协议与防死循环护栏；将同步阻塞的 `agent/core.py` 演进为支持单会话互斥、工作副本原子提交、高危工具挂起审批（Human-in-the-Loop）与恢复续关的异步状态机引擎；并分别对外提供异步流式 CLI 与 FastAPI + SSE Web 服务网关。
- **阶段状态**：⏳ 进行中（已完成 **11.1**，准备开始 **11.2**）

---

## 环节进度

| 环节 | 主题 | 状态 | 提交 Hash |
| :---: | :--- | :---: | :--- |
| 11.1 | 统一事件流协议与护栏 | ✅ 已完成 | `study(stage-11.1)` |
| 11.2 | 异步状态机引擎与 HITL 检查点 | ⏳ 待开始 | - |
| 11.3 | 异步流式 CLI 升级 | ⬜ 待开始 | - |
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
- **状态**：⬜ 待开始
- **预习知识点导览**：
  - 单会话互斥与工作副本事务提交（中途报错不污染存档）；
  - 命中 `HIGH_RISK` 工具时保存 `PendingApproval` 挂起并返回 `approval_required`，通过 `resume()` 批准执行或拒绝回填；
  - 达到 `max_steps` 时切无工具模式强制模型收尾总结。
- **改动文件**：`agent/engine/core.py`、`agent/factory.py`（待手敲）

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
