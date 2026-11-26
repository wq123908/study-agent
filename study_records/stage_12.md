# 阶段 12 学习记录：自动化测试套件与回归评测流水线

- **目标**：搭建不花钱、不联网、1 秒跑完的离线自动化测试套件（覆盖工具、记忆、状态机、HITL、重试降级与 FastAPI 接口）；构建包含黄金用例集、确定性回放与混沌故障注入（`FaultInjector`）的自动化回归评测门禁流水线，正式为 12 阶段通用 Agent 底层框架收官。
- **阶段状态**：✅ 已完成（**12.1 ～ 12.2** 全部验收通过，阶段 1～12 通用企业级 Agent 底层框架 100% 圆满收官！）

---

## 环节进度

| 环节 | 主题 | 状态 | 提交 Hash |
| :---: | :--- | :---: | :--- |
| 12.1 | 离线单元测试与端到端测试 | ✅ 已完成 | `2cf70ab` |
| 12.2 | 黄金评测集与门禁流水线 | ✅ 已完成 | `study(stage-12.2)` |

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
- **状态**：✅ 已完成（四项 SLA 门禁全达标 + 51 条 pytest 全绿，耗时约 4 分钟：`2026-11-26 18:03 ~ 18:07`，阶段 1～12 全线圆满毕业！）
- **改动文件**：`eval/__init__.py`、`eval/datasets/golden_cases.jsonl`、`eval/run_eval.py`、`tests/test_llm.py`
- **学习知识点详解**：
  1. **12 道黄金基准考卷（`eval/datasets/golden_cases.jsonl`）**：覆盖工具轨迹、多工具并发、L3 长期记忆读写、直接问答、HITL 批准/拒绝、畸形参数自愈、首次超时混沌自愈与 AST 注入安全拦截。
  2. **离线确定性回放 + `--live` 真模型双模评测（`eval/run_eval.py`）**：
     - `ReplayLLM` 支持 `{tool_0}` / `{tool_1}` 占位符自动注入真实工具执行结果，保证离线 CI 门禁 0 成本秒跑；传入 `--live` 即刻切真实 DeepSeek 端到端评估；
     - 复用 9.4 `ToolExecutor.fault_injector` 实现一次性混沌超时注入（`inject_first_timeout`），专门考察 Agent 异常自愈率；
     - `score_faithfulness()` 确定性检查期望关键事实与工具输出一致性；
     - 四项硬性 SLA 门禁（轨迹召回率 ≥ 95%、非法幻觉工具率 == 0%、平均忠实度 ≥ 4.5/5.0、故障自愈率 ≥ 85%），通过返回退出码 `0`，失败返回 `1` 直接阻断 CI/CD。
  3. **评测门禁融入单元测试（`tests/test_llm.py`）**：新增 `test_golden_evaluation_suite_passes_all_sla_gates()`，运行 `py -m pytest -q` 一键连带验过全套 SLA 门禁。
- **验收命令与结果**：
  - `py -m eval.run_eval`：
    - 12 道考题全部 `PASS`
    - 工具轨迹召回率：`100.0%`（SLA ≥ 95%）
    - 非法幻觉工具率：`0.0%`（SLA == 0%）
    - 平均事实忠实度：`5.00 / 5.0`（SLA ≥ 4.5）
    - 故障自愈成功率：`100.0%`（SLA ≥ 85%）
    - 端到端延迟 P95：`220.6 ms`
    - 门禁结论：`✅ 全部达标 (PASSED)`
  - `py -m pytest -q` → `51 passed in 2.11s`。
- **掌握情况与踩坑记录**：全部一次性零失误通过！通用企业级 Agent 底层框架（阶段 1～12，总计 5,012 行代码）100% 闭环收官，下一步正式切入业务实战分支 `feat/coldchain-agent` 落地《供应链冷链异常履约与协同 Agent》！
