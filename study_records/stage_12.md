# 阶段 12 学习记录：自动化测试套件与回归评测流水线

- **目标**：搭建不花钱、不联网、1 秒跑完的离线自动化测试套件（覆盖工具、记忆、状态机、HITL、重试降级与 FastAPI 接口）；构建包含黄金用例集、确定性回放与混沌故障注入（`FaultInjector`）的自动化回归评测门禁流水线，正式为 12 阶段通用 Agent 底层框架收官。
- **阶段状态**：⏳ 进行中（准备开始 **12.1**）

---

## 环节进度

| 环节 | 主题 | 状态 | 提交 Hash |
| :---: | :--- | :---: | :--- |
| 12.1 | 离线单元测试与端到端测试 | ⏳ 待开始 | - |
| 12.2 | 黄金评测集与门禁流水线 | ⬜ 待开始 | - |

---

## 12.1 离线单元测试与端到端测试
- **状态**：⏳ 待开始
- **预习知识点导览**：
  - `pyproject.toml` 项目工程化与 `pytest` 配置；
  - `tests/conftest.py` 共享 `ScriptedLLM` 假大脑与通用测试夹具；
  - 覆盖工具层、L1/L2/L3 分层记忆、状态机/HITL/护栏、AsyncLLM 重试降级与 FastAPI HTTP/SSE 接口的完整离线单测。
- **改动文件**：`pyproject.toml`、`tests/conftest.py`、`tests/test_*.py`（待手敲）

## 12.2 黄金评测集与门禁流水线
- **状态**：⬜ 待开始
- **预习知识点导览**：
  - `eval/datasets/golden_cases.jsonl` 黄金基准考卷（必选工具轨迹、期望关键词、混沌故障自愈用例）；
  - `eval/run_eval.py` 确定性回放（`ReplayLLM`）+ `--live` 实测、四项 SLA 指标（轨迹召回率 / 非法工具率 / 忠实度 / 混沌自愈率）与门禁报表。
- **改动文件**：`eval/__init__.py`、`eval/datasets/golden_cases.jsonl`、`eval/run_eval.py`（待手敲）
