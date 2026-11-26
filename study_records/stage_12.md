# 阶段 12 学习记录：自动化测试套件与回归评测流水线

- **目标**：搭建不花钱、不联网、1 秒跑完的离线自动化测试套件（覆盖工具、记忆、状态机、HITL、重试降级与 FastAPI 接口）；构建包含黄金用例集、确定性回放与混沌故障注入（`FaultInjector`）的自动化回归评测门禁流水线，正式为 12 阶段通用 Agent 底层框架收官。
- **阶段状态**：⏳ 进行中（已完成 **12.1**，准备开始收官战 **12.2**）

---

## 环节进度

| 环节 | 主题 | 状态 | 提交 Hash |
| :---: | :--- | :---: | :--- |
| 12.1 | 离线单元测试与端到端测试 | ✅ 已完成 | `study(stage-12.1)` |
| 12.2 | 黄金评测集与门禁流水线 | ⏳ 待开始 | - |

---

## 12.1 离线单元测试与端到端测试
- **状态**：✅ 已完成（50 条离线单测一次性全绿通过，耗时约 8 分钟：`2026-11-26 17:55 ~ 18:03`，并清理 5 个历史旧文件）
- **改动文件**：`pyproject.toml`、`tests/__init__.py`、`tests/conftest.py`、`tests/test_tools.py`、`tests/test_memory.py`、`tests/test_engine.py`、`tests/test_api.py`、`tests/test_llm.py`（并移除遗留旧文件 `agent/core.py`、`check_step2~5.py`）
- **学习知识点详解**：
  1. **工程化测试配置与剧本假大脑底座（`pyproject.toml` / `tests/conftest.py`）**：开启 `asyncio_mode = "auto"` 免除重复异步标记；构造 `ScriptedLLM` 与 `make_agent` 夹具实现 0 费用、0 联网、100% 确定可复现测试。
  2. **五大核心测试面全覆盖**：
     - `test_tools.py`：AST 安全计算器参数化注入拦截、Schema 隐藏 `ctx`、Pydantic 参数自愈、4 并发耗时验证、故障注入与沙箱路径穿越拦截；
     - `test_memory.py`：轮次边界裁剪、孤立 `tool` 清洗、JSON 原子存储、BM25 长期记忆用户隔离与 L2 滚动摘要防覆盖；
     - `test_engine.py`：流式吐字、全轨迹落盘、失败原子回滚、重复调用护栏、最大步数缴械收尾、HITL 批准/拒绝、`session_busy` 并发互斥与参数纠偏自愈；
     - `test_api.py`：FastAPI `TestClient` 覆盖 `/healthz`、SSE 事件解析、HTTP HITL 审批写盘、会话查删与 `X-API-Key` 401 鉴权；
     - `test_llm.py`：`monkeypatch` 跳过退避等待测试 `AsyncLLM` 分片拼接/主备降级/耗尽报错、JSONL Trace 瀑布图与 `Config.validate()`（使用正版 `httpx` 避开 `httpx2` 拼写坑）。
- **验收命令与结果**：
  - `py -m pytest -q` → `50 passed in 2.04s`（零失败、零跳过）。
- **掌握情况与踩坑记录**：全套 50 个测试用例 2 秒一次性全绿！同时完成仓库瘦身清理，下一步开启最后一小节 **12.2 黄金评测集与门禁流水线**。

## 12.2 黄金评测集与门禁流水线
- **状态**：⬜ 待开始
- **预习知识点导览**：
  - `eval/datasets/golden_cases.jsonl` 黄金基准考卷（必选工具轨迹、期望关键词、混沌故障自愈用例）；
  - `eval/run_eval.py` 确定性回放（`ReplayLLM`）+ `--live` 实测、四项 SLA 指标（轨迹召回率 / 非法工具率 / 忠实度 / 混沌自愈率）与门禁报表。
- **改动文件**：`eval/__init__.py`、`eval/datasets/golden_cases.jsonl`、`eval/run_eval.py`（待手敲）
