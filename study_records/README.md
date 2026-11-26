# study-agent 学习档案与接续指南

> 本文件夹用于持久记录你在 `study-agent` 项目中的**完整学习路线、当前进度、每个环节掌握情况与代码成果**。
> 无论是你隔天回来继续写，还是切换新的 AI 助手接手，**只需先读本文件与对应的 `stage_XX.md`**，即可立刻接上进度。

---

## 1. 当前状态快照（随时更新）

- **当前主线 Git 分支**：`study/stage-9-12`（基于 `v0.1.0-basic` 切出，推进阶段 9～12 通用 Agent 基层框架）
- **后续业务实战分支**：`feat/coldchain-agent`（已建立并归档目标岗位 JD、《供应链冷链异常履约与协同 Agent》12 页 PDF 原件、完整 Markdown 转写版及 2026-11-22 路线决策聊天记录；详见 [`./coldchain_agent/README.md`](./coldchain_agent/README.md)）
- **对照参考分支**：`main`（Tag `v0.2.0`，包含 9～12 阶段成品实现，仅作对照参考，不直接覆盖当前分支）
- **当前已完成**：阶段 1 ～ 阶段 11（基础版 + 阶段 9 工具与 Trace 底座 + 阶段 10 AsyncLLM 与三级记忆 + 阶段 11 异步状态机、HITL 审批、流式 CLI 与 FastAPI SSE 网关）
- **正在进行**：**阶段 12 —— 离线单测套件与自动化回归评测流水线**（已完成 `12.1`，准备开始最后一战 `12.2`）
- **下一个待做环节**：**12.2 黄金评测集与门禁流水线**（`eval/datasets/golden_cases.jsonl`、`eval/run_eval.py` 确定性回放与 `--live` 实测、四项 SLA 指标与 `FaultInjector` 混沌自愈门禁；见 [`stage_12.md`](./stage_12.md)）
- **总体两步走战略**：
  1. **第一步（当前主线）**：在 `study/stage-9-12` 完整敲完阶段 10～12，让通用 Agent 基层框架 100% 闭环收官（讲解时用大白话，并顺带点明每个模块在后续供应链冷链 Agent 中的业务用法）；
  2. **第二步（业务分支）**：12 阶段完成后切至 `feat/coldchain-agent` 分支，在基层框架之上落地《供应链冷链异常履约与协同 Agent》（详见 [`./coldchain_agent/README.md`](./coldchain_agent/README.md) 与 [`./coldchain_agent/coldchain_agent_sdd.md`](./coldchain_agent/coldchain_agent_sdd.md)）。

---

## 2. 给下一任 AI 助手的接续规则（必须遵守）

当你接手本仓库继续带用户学习时，请严格按以下工作流推进：

1. **先读状态再开口**：先读取 [`README.md`](./README.md)、[`curriculum.md`](./curriculum.md) 以及当前阶段记录（如 `stage_09.md`），确认用户已完成了哪一节、卡在什么地方、掌握程度如何。
2. **坚持教练式带写**（详见 [`../.trae/skills/agent-build-coach/SKILL.md`](../.trae/skills/agent-build-coach/SKILL.md)）：
   - **不要直接修改业务代码文件**（`agent/`、`app/`、`main.py`、`eval/`、`tests/` 等），除非用户明确说“你直接改”。
   - 代码在对话中给出（标明目标文件路径、完整代码与逐行/关键行解释，不使用 `...` 省略；**多参数定义、构造与调用严格“一个参数占一行”**，单轮代码控制在 60 行以内），由用户亲手敲进编辑器。
   - **一次只讲一个环节（或一个子步骤）**，严格按顺序：**【全局定位】本模块在整个系统里的位置与上下游串联（大白话垂直流程图）→ 文本图解（复杂状态/流程可辅以交互图解）+ 大白话讲透原理与内部每个方法写法 + 点明冷链 Agent 业务用法 → 说位置 → 给代码 → 给运行命令 → 给明确验收标准 → 停下等用户贴出执行结果**。
   - `main` 分支（`v0.2.0`）是成品参考；教学时优先引导用户理解并自己实现，遇到排查困难时可参考对照，但不要直接把 `main` 的代码整包复制覆盖练习分支。
3. **每个环节验收通过后的固定收尾动作**：
   - 更新对应 `stage_XX.md`：如实记录本环节**学了什么知识点**、**改了哪些文件**、**实际运行输出/验收情况**、**踩过的坑与掌握程度**；
   - 更新 [`curriculum.md`](./curriculum.md) 与本文件顶部的“当前状态快照”；
   - 执行一次 `git add` 与 `git commit`（建议提交信息格式：`study(stage-X.Y): <环节主题>`），把**用户手写的代码 + 学习档案更新**一起固化到 Git 历史中。

---

## 3. 总进度看板

| 阶段 | 主题 | 状态 | 学习记录文档 | 对应提交 |
| :--- | :--- | :---: | :--- | :--- |
| 阶段 1～8 | 从零构建可运行的单机 ReAct Agent（基础版） | ✅ 已完成 | [`stage_01_08_review.md`](./stage_01_08_review.md) | `1c0707e` / `v0.1.0-basic` |
| 阶段 9 | 基线修复、声明式安全工具层与全链路 Trace 底座 | ✅ 已完成 | [`stage_09.md`](./stage_09.md) | `f40398e` ～ `ed3f972` |
| 阶段 10 | AsyncLLM 流式聚合与 L1/L2/L3 分层记忆 | ✅ 已完成 | [`stage_10.md`](./stage_10.md) | `b6c5b60` ～ `study(stage-10.4)` |
| 阶段 11 | 异步流式 ReAct 状态机、HITL 审批与 FastAPI SSE | ✅ 已完成 | [`stage_11.md`](./stage_11.md) | `23dcf74` ～ `study(stage-11.4)` |
| 阶段 12 | 离线单测套件与自动化回归评测流水线 | ⏳ 进行中（已完成 12.1，待 12.2） | [`stage_12.md`](./stage_12.md) | `study(stage-12.1)` |
| **业务实战篇**<br>（`feat/coldchain-agent`） | **供应链冷链异常履约与协同 Agent（ColdChain-Agent）**<br>（5 张业务表 + 7 个插件 + 条款级 RAG + 7 节点混合控制状态机与 HITL + 40 条黄金评测） | 🗂️ 已立项归档（待阶段 12 收官后切分支实施） | [`./coldchain_agent/README.md`](./coldchain_agent/README.md)<br>[`./coldchain_agent/coldchain_agent_sdd.md`](./coldchain_agent/coldchain_agent_sdd.md) | - |

---

## 4. 目录结构说明

- `study_records/README.md`：本文件，全局状态看板与下一任 AI 接续协议
- `study_records/curriculum.md`：阶段 1～12 完整课程大纲与逐节知识点清单
- [`stage_01_08_review.md`](./stage_01_08_review.md)：第 1～8 阶段成果回顾与现存基线问题诊断
- `study_records/stage_09.md`（及后续 `stage_10.md`、`stage_11.md`、`stage_12.md`）：分阶段逐节学习笔记、验收实录与掌握度复盘
- [`study_records/time_log.md`](./time_log.md)：精细学习时长打卡日志与历史里程碑时间轴
- [`./coldchain_agent/`](./coldchain_agent/README.md)：**业务实战分支专属档案库**（含目标岗位 JD 截图、`ColdChain-Agent` 12 页 PDF 原件、完整 Markdown 转写版设计文档及 2026-11-22 聊天记录）
