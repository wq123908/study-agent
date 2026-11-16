# 阶段 1 ～ 8 学习成果复盘与基线盘点

- **对应版本 / 标签**：`v0.1.0-basic`（提交 `1c0707e` + `4130eb8`）
- **阶段状态**：✅ 已完成，已切出 `study/stage-9-12` 分支准备向企业级演进

---

## 1. 已掌握的知识与实现成果

前 8 个阶段不依赖任何 Agent 框架，亲手搭出了一个完整可跑通的单机 CLI 智能体：

| 模块 | 当前实现 | 已验证掌握的能力 |
| :--- | :--- | :--- |
| [`../agent/config.py`](../agent/config.py) | `dotenv` 加载 `.env`，返回 `Config(api_key, base_url, model)` | 配置与业务代码分离 |
| [`../agent/message.py`](../agent/message.py) | `@dataclass Message(role, content)` + `to_dict()` | 消息结构与角色常量抽象 |
| [`../agent/llm.py`](../agent/llm.py) | 同步 `OpenAI` 客户端封装 `LLM.request(messages, tools)` | 理解兼容 OpenAI Chat Completions 协议及 `tools or None` 兼容 |
| [`../agent/memory.py`](../agent/memory.py) | `Memory` 读写 `memory.json`，`trim(max_count=40)` 保留第 0 条 system + 尾部长窗口 | 会话跨进程持久化与基础防溢出裁剪 |
| [`../agent/tools.py`](../agent/tools.py) | `get_current_time`、`calculator`、手写 `TOOLS` Schema 与 `TOOL_MAP` | Function Calling 协议与工具分发本质 |
| [`../agent/core.py`](../agent/core.py) | `Agent.chat()` 与 `_think()`（`MAX_STEP=5` 循环执行工具并回填 `role="tool"`） | ReAct（思考 → 调工具 → 观察结果 → 再推理）主闭环 |
| [`../main.py`](../main.py) | `logging.basicConfig` + `while True` 交互输入 + `try/except` 兜底 | 交互式 CLI 生命周期与单轮容错 |
| [`../check_env.py`](../check_env.py)、`check_step2~5.py` | 各阶段独立验收脚本 | 分阶段独立验证习惯 |

---

## 2. 当前基线（`v0.1.0-basic`）存在的明确问题

这些问题将在 **阶段 9 ～ 12** 中逐一亲手解决：

1. **配置空指针崩溃**：`agent/config.py` 中 `os.getenv("DEEPSEEK_API_KEY").strip()` 在未配置变量时直接抛出 `AttributeError`；且默认模型为不存在/旧命名 `deepseek-flash`（`.env.example` 为 `deepseek-v4-flash`）。
2. **工具安全与死代码隐患**：`agent/tools.py` 的 `calculator` 使用 `eval(expression, {"__builtins__": None})` 仍存在沙箱逃逸风险，且 `except` 后面有一行永远执行不到的死代码 `return str(result)`；手写 `TOOLS` Schema 与函数签名割裂。
3. **单轮记忆非原子 & 丢工具轨迹**：`agent/core.py` 先 `self.messages.append(USER)` 再跑 `_think()`，若模型调用异常会残留孤立的 `user` 消息；同时工具调用过程只存在 `_think()` 局部变量 `history` 里，未写入 `memory.json`。
4. **窗口裁剪风险**：`agent/memory.py` 仅按条数 `max_count=40` 切片，一旦持久化工具消息，切掉 `assistant(tool_calls)` 而留下孤立 `tool` 消息会导致 API 400 报错；也缺少长对话摘要和跨会话事实记忆。
5. **同步阻塞与无用导入**：`agent/llm.py` 多了未使用的 `from multiprocessing import context` 和 `Message`；同步阻塞无法流式推送，也无重试/降级与人工审批挂起能力。
6. **验收脚本脱节**：`check_step2.py` 和 `check_step3.py` 因 `Agent.__init__` 新增必填参数 `memory` / `tools` 已无法直接运行；缺少自动化测试与评测体系。
