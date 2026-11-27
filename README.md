# study-agent 基础版

## 项目介绍

基于 Python 的命令行 Agent，实现多轮对话、模型工具调用和本地记忆。运行时通过 ReAct 循环将工具调用结果回传模型，并将完成的对话保存到本地。

| 能力 | 实现及入口 |
| --- | --- |
| 多轮对话 | CLI 负责组件组装、输入处理和异常提示。 [程序入口](main.py) |
| 模型接入 | 通过 OpenAI 兼容 Chat Completions 接口调用模型。服务地址、模型名称和密钥由环境配置提供。 [模型客户端](agent/llm.py) · [配置](agent/config.py) |
| 工具调用 | 定义模型可用的函数 Schema，通过工具名映射调用时间查询和计算器。运行时解析 JSON 参数，以 `tool_call_id` 关联请求与结果。 [工具定义](agent/tools.py) · [运行时](agent/core.py) |
| 执行约束 | 单轮 ReAct 循环最多调度 5 步，达到上限后结束本轮。 [运行时](agent/core.py) |
| 本地记忆 | 使用 JSON 保存并恢复对话。模型请求前裁剪历史窗口，最多保留 40 条对话消息，包含系统消息。 [记忆模块](agent/memory.py) |

## 项目进度

基础版已完成命令行交互、模型接入、工具调用和会话持久化。代码基线为 `4130eb8`，对应标签 `v0.1.0-basic`，已验证依赖安装与 CLI 启停。

## 运行说明

使用 Python 3.11 或更高版本，在项目根目录执行以下 PowerShell 命令。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在 `.env` 中填写 `DEEPSEEK_API_KEY`，并按模型服务配置 `DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL`。执行 `.\.venv\Scripts\python.exe main.py` 启动 CLI，输入 `exit` 退出。
