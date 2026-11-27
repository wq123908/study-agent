# V2.0 Gemini 接续说明

文档准备日期为 2026-11-27。仓库位于 `C:\Users\admin\.gemini\antigravity\scratch\study-agent`，开发分支为 `main`。当前 V2.0 文档已就绪，代码从 **13.1 独立运行记录**开始。

## 先读取的文件

1. [学习索引](README.md)，确认当前接续点和带写方式。
2. [课程大纲](curriculum.md)，理解阶段 13–18 的前后依赖。
3. [阶段 13](stage_13.md)，从第一个未通过的子步骤开始。
4. 现有 `agent/state.py`、`agent/engine/core.py`、`agent/factory.py` 和 `tests/conftest.py`，理解会话、执行入口、依赖注入及离线模型。
5. [项目 README](../README.md)，核对版本目标。根 README 面向正式项目介绍，学习过程记录在本目录。

## 本轮起点

| 项目 | 当前事实 |
| --- | --- |
| V1.0 基线 | `542fa2b`，已有 CLI、Web、流式 ReAct、分层记忆、工具执行、审批、Trace 和离线回归。 |
| 文档准备前的主分支提交 | `0adb022`。接续时以实际 Git 状态重新核对。 |
| V2.0 代码进度 | 待开始。 |
| 第一模块 | `agent/run_state.py`，建议使用 `RunRecord` 与 `RunPhase`。 |
| 第一轮范围 | 13.1a 的职责、枚举和记录字段。 |
| 后续范围 | 序列化、任务输入、任务结果与离线联验，逐节展开。 |

现有 `agent/state.py` 的 `RunStatus` 由会话状态使用。新的运行记录使用独立类型。V1.0 的审批恢复走独立的 Trace，阶段 14 再把这些执行尝试关联到原任务的 `run_id`。这些边界在开始定义新模型时讲清楚。

## 启动核对

先在项目根目录确认分支和解释器。

```powershell
git status --short --branch
git log -1 --oneline
python --version
```

若项目已有虚拟环境，则优先检查并使用它。

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m eval.run_eval
```

解释器由环境中的实际可用路径决定。保留已有用户修改，阅读差异后继续。V1.0 的 52 项测试和 12 条离线回放是基线，接续时将本次实际输出与基线比较。

## 可以直接发给 Gemini 的提示词

> 请接续当前 study-agent 仓库的 V2.0。
>
> 请先读 `study_records/README.md`、`study_records/curriculum.md`、`study_records/stage_13.md` 和本文件，再核对 `main`、当前未提交修改、Python 解释器以及相关源码。
>
> 沿用此前 V1.0 的教练式带写方式。我亲手录入代码，你在对话中逐模块讲解。一次只展开一个子步骤，先讲模块在系统中的位置，再用大白话讲原理，给出准确的目标文件和完整代码，最后给可执行的运行命令、预期结果和验收标准，等我贴出结果再继续。
>
> 每轮代码最多 60 行，多参数的定义、构造与调用一个参数一行。长模块分为可以单独验收的步骤。请根据已存在代码复用接口，按需使用离线模型和临时目录验证。
>
> 当前从 13.1a 开始。先说明会话、单次运行与 Trace 的关系，然后给 `agent/run_state.py` 中 `RunPhase` 和 `RunRecord` 的第一步。序列化、任务请求、结果契约按大纲逐步推进。
>
> 每节通过后，记录实际文件、输出、问题和掌握情况，更新阶段记录、课程大纲和学习索引。提交前核对差异，只提交本节相关文件。耗时、测试结果和提交号以实际证据填写。根 README 用正式项目口吻记录功能与进度。
