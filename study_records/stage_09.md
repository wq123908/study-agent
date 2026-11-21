# 阶段 9 学习记录：基线修复、声明式安全工具层与全链路 Trace 底座

- **目标**：修复第 8 阶段代码里的基线缺陷，将工具层重构为自动生成 Schema + Pydantic 校验 + AST 安全计算 + 并发超时控制，并建立可观测 Trace 底座。
- **阶段状态**：⏳ 进行中（已完成 **9.1**，准备开始 **9.2**）

---

## 环节进度

| 环节 | 主题 | 状态 | 提交 Hash |
| :---: | :--- | :---: | :--- |
| 9.1 | 基线止血与强类型配置 | ✅ 已完成 | `f40398e` + 收尾提交 |
| 9.2 | 完整消息协议模型（`ToolCallItem` / 双序列化） | ⏳ 待开始 | - |
| 9.3 | AST 安全计算器（替代 `eval`） | ⬜ 待开始 | - |
| 9.4 | 声明式工具注册表与异步并发执行器 | ⬜ 待开始 | - |
| 9.5 | 全链路 `Trace → Span` 与结构化日志 | ⬜ 待开始 | - |

---

## 9.1 基线止血与强类型配置
- **状态**：✅ 已完成（第 1～3 步全部验收通过）
- **学习知识点**：`ConfigError(RuntimeError)` 自定义领域异常、`(os.getenv(name) or "").strip() or default` 空指针与空串防御、`_env_int` / `_env_float` / `_env_list` 强类型解析与 `from exc` 异常链、`field(default_factory=...)` 防可变默认值共享、`@property` 基于 `data_dir` 派生路径、`Config.validate()` 启动边界门禁、`require_api_key=False` 离线开关、`agent/llm.py` 配置透传（`temperature` / `request_timeout`）与 `.env` / `.env.example` / `.gitignore` 安全隔离
- **改动文件**：`agent/config.py`、`agent/llm.py`、`.env.example`、`.gitignore`
- **验收命令与结果**：
  - 第 1 步：`python -c "from agent.config import load_config; print(load_config(require_api_key=False)); load_config()"` → 正常打印默认 `Config`，缺失 `.env` 时抛出 `ConfigError: 请在项目根目录 .env 中填写真实的 DEEPSEEK_API_KEY`（不再 `AttributeError`）
  - 第 2 步：`python -c "from agent.config import Config, load_config; c = load_config(require_api_key=False); print('model:', c.model, '| sessions_dir:', c.sessions_dir, '| max_steps:', c.max_steps); Config(api_key='', max_steps=0).validate()"` → 输出 `model: deepseek-chat | sessions_dir: data\sessions | max_steps: 8` 且成功拦截 `ConfigError: AGENT_MAX_STEPS 必须 >= 1`
  - 第 3 步：`python check_env.py` + `load_config()` + `LLM(cfg)` 联调 → `check_env.py` 输出正常；`get_type_hints(LLM.request)` 为 `{'messages': list[dict], 'tools': list | None}`；输出 `model: deepseek-flash | temp: 0.3 | timeout: 60.0`；`git status -s` 未追踪 `.env`
- **掌握情况与踩坑记录**：
  - 第 1 步手敲时曾将 `.strip()` 误敲为 `,strip()` 引发 `NameError`，并将 `_env_int` 与 `_env_float` 写串；
  - 第 3 步曾误将配置与真实 API Key 写入受 Git 追踪的 `.env.example`（已及时撤回并新建本地 `.env`），以及在 `agent/llm.py` 手敲出 `message:list[dist]` 拼写误差（已借助 `from __future__ import annotations` 差异认知与 `get_type_hints` 排查修正），也实践了 `.env` 拼写排查（`deepseek-falsh` → `deepseek-flash`）。现已完整掌握强类型配置、环境变量隔离与客户端参数透传。

## 9.2 完整消息协议模型
- **状态**：⬜ 待开始
- **学习知识点**：
- **改动文件**：
- **验收命令与结果**：
- **掌握情况与踩坑记录**：

## 9.3 AST 安全计算器
- **状态**：⬜ 待开始
- **学习知识点**：
- **改动文件**：
- **验收命令与结果**：
- **掌握情况与踩坑记录**：

## 9.4 声明式工具注册表与异步并发执行器
- **状态**：⬜ 待开始
- **学习知识点**：
- **改动文件**：
- **验收命令与结果**：
- **掌握情况与踩坑记录**：

## 9.5 全链路 Trace 与结构化日志
- **状态**：⬜ 待开始
- **学习知识点**：
- **改动文件**：
- **验收命令与结果**：
- **掌握情况与踩坑记录**：
