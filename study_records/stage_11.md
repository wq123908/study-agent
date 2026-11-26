# 阶段 11 学习记录：异步流式 ReAct 状态机、HITL 人工审批与 FastAPI SSE

- **目标**：构建统一事件流协议与防死循环护栏；将同步阻塞的 `agent/core.py` 演进为支持单会话互斥、工作副本原子提交、高危工具挂起审批（Human-in-the-Loop）与恢复续关的异步状态机引擎；并分别对外提供异步流式 CLI 与 FastAPI + SSE Web 服务网关。
- **阶段状态**：⏳ 进行中（准备开始 **11.1**）

---

## 环节进度

| 环节 | 主题 | 状态 | 提交 Hash |
| :---: | :--- | :---: | :--- |
| 11.1 | 统一事件流协议与护栏 | ⏳ 待开始 | - |
| 11.2 | 异步状态机引擎与 HITL 检查点 | ⬜ 待开始 | - |
| 11.3 | 异步流式 CLI 升级 | ⬜ 待开始 | - |
| 11.4 | FastAPI + SSE Web 网关 | ⬜ 待开始 | - |

---

## 11.1 统一事件流协议与护栏
- **状态**：⏳ 待开始
- **预习知识点导览**（完成后补充实操细节与踩坑记录）：
  - **统一事件流协议（`AgentEvent`）**：`.to_dict()` 与 `.to_sse()` 将引擎内部状态（`step_start` / `content_delta` / `tool_start` / `approval_required` / `done` / `error`）解耦成标准小纸条，CLI 和 Web 前端共用同一条流。
  - **死循环护栏（`LoopGuard`）与输入护栏（`validate_user_input`）**：规范化参数哈希抓出重复调参，二次触发注入纠偏、达上限熔断；拦截空白与超长输入。
- **改动文件**：`agent/engine/__init__.py`、`agent/engine/events.py`、`agent/engine/guardrails.py`（待手敲）
- **验收命令与结果**：
- **掌握情况与踩坑记录**：

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
