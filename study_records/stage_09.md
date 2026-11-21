# 阶段 9 学习记录：基线修复、声明式安全工具层与全链路 Trace 底座

- **目标**：修复第 8 阶段代码里的基线缺陷，将工具层重构为自动生成 Schema + Pydantic 校验 + AST 安全计算 + 并发超时控制，并建立可观测 Trace 底座。
- **阶段状态**：⏳ 进行中（已完成 **9.1**，准备开始 **9.2**）

---

## 环节进度

| 环节 | 主题 | 状态 | 提交 Hash |
| :---: | :--- | :---: | :--- |
| 9.1 | 基线止血与强类型配置 | ✅ 已完成 | `f40398e` / `7f67b7c` |
| 9.2 | 完整消息协议模型（`ToolCallItem` / 双序列化） | ⏳ 待开始 | - |
| 9.3 | AST 安全计算器（替代 `eval`） | ⬜ 待开始 | - |
| 9.4 | 声明式工具注册表与异步并发执行器 | ⬜ 待开始 | - |
| 9.5 | 全链路 `Trace → Span` 与结构化日志 | ⬜ 待开始 | - |

---

## 9.1 基线止血与强类型配置
- **状态**：✅ 已完成（第 1～3 步全部验收通过）
- **改动文件**：`agent/config.py`、`agent/llm.py`、`.env.example`、`.gitignore`
- **学习知识点详解**：
  1. **自定义领域异常 `ConfigError(RuntimeError)`**：
     - 继承 `RuntimeError` 定义专属配置异常，替代裸露的 `RuntimeError` 或误触发的 `AttributeError` / `ValueError`。
     - 上层入口（如 CLI `main.py`、Web 启动阶段）可精准 `except ConfigError`，把“缺少密钥/参数越界”与“运行时网络错误”区分开，输出人类可读的诊断信息。
  2. **环境变量空指针与空白串防御（`_env_str`）**：
     - 写法：`(os.getenv(name) or "").strip() or default`。
     - 为什么不用 `os.getenv(name, default).strip()`：当变量**存在但值为空串或纯空格**（如 `DEEPSEEK_MODEL=   `）时，`os.getenv(name, default)` 会原样返回 `"   "` 而不会回退到 `default`；而直接 `.strip()` 在变量缺失（返回 `None`）时又会抛 `AttributeError`。上述写法同时兜底了 `None`、空串和纯空格三种情况。
  3. **强类型解析与异常链保留（`_env_int` / `_env_float` / `_env_list` + `from exc`）**：
     - 环境变量天然是字符串，在配置加载层集中转成 `int` / `float` / `list[str]`（列表按逗号分割并过滤空项：`[item.strip() for item in _env_str(name).split(",") if item.strip()]`），避免非法配置潜伏到运行深处才爆出 `TypeError`。
     - 解析失败时通过 `raise ConfigError(f"环境变量 {name} ..., 当前值: {raw!r}") from exc` 抛出，既精准指明出错变量名与原始值（`!r` 能暴露隐藏空格或引号），又通过 `from exc` 保留底层 `ValueError` 异常链。
  4. **`dataclass` 可变默认值隔离（`field(default_factory=...)`）**：
     - 写法：`data_dir: Path = field(default_factory=lambda: Path("data"))`、`api_keys: list[str] = field(default_factory=list)`。
     - 原理：避免多个 `Config` 实例共享同一个可变对象（如 `list`）造成跨实例状态污染；传入工厂函数（注意不要加括号立即调用），确保每次实例化都生成独立对象。
  5. **单一数据源（SSOT）与 `@property` 派生路径**：
     - 只把根目录 `data_dir` 作为配置项，把 `sessions_dir`、`traces_dir`、`workspace_dir`、`long_term_path` 定义为 `@property` 动态拼接 `self.data_dir / "..."`。
     - 价值：测试或切换环境只需改 `AGENT_DATA_DIR` 一个变量，所有落盘路径自动同步，杜绝“部分数据写进测试目录、另一部分写进生产目录”的配置漂移。
  6. **启动边界门禁（`Config.validate()`）与离线测试开关（`require_api_key`）**：
     - **Fail-Fast（快速失败）**：`load_config()` 返回前链式调用 `.validate()`，集中校验范围约束（`max_steps >= 1`、`context_max_tokens >= 500`、`0.0 <= temperature <= 2.0`）以及占位符拦截（`api_key.startswith("sk-your-key")`），把问题拦截在启动第 0 秒。
     - **可测性解耦**：提供 `require_api_key: bool = True` 开关，使离线单测和 `check_env.py` 在无真实密钥时也能复用同一套配置解析与边界校验逻辑。
  7. **`from __future__ import annotations` 延迟注解求值（踩坑延伸）**：
     - 在文件首行开启后，Python 在模块导入与函数定义时**不会立刻对类型注解求值**，而是把注解存成字符串。
     - 注意点：因此把 `list[dict]` 误写成 `list[dist]` 时导入阶段不会报错，只有在调用 `typing.get_type_hints()` 或运行静态检查（mypy/pyright）时才会触发 `NameError`。
  8. **配置贯通下游与死代码清理（`agent/llm.py`）**：
     - 清除早期遗留的未用导入（`from multiprocessing import context`、`Message`）；
     - 取消 `temperature=0.7` 硬编码，改传 `self.config.temperature`，并为 `OpenAI(...)` 传入 `timeout=config.request_timeout`，防止远端无响应导致请求无限挂起。
  9. **本地配置与仓库安全隔离（`.env` / `.env.example` / `.gitignore`）**：
     - `load_dotenv()` 只加载项目根目录 `.env`，**不会加载 `.env.example`**；
     - `.env.example` 受 Git 追踪，只保留字段说明与 `sk-your-key-here` 占位符，严禁写入真实密钥；
     - `.gitignore` 覆盖 `.env`、`memory*.json`、`data/` 与 `.pytest_cache/`，防止敏感凭据、运行时记忆与测试缓存误提交。
- **验收命令与结果**：
  - 第 1 步：`python -c "from agent.config import load_config; print(load_config(require_api_key=False)); load_config()"` → 正常打印默认 `Config`，缺失 `.env` 时抛出 `ConfigError: 请在项目根目录 .env 中填写真实的 DEEPSEEK_API_KEY`（不再 `AttributeError`）
  - 第 2 步：`python -c "from agent.config import Config, load_config; c = load_config(require_api_key=False); print('model:', c.model, '| sessions_dir:', c.sessions_dir, '| max_steps:', c.max_steps); Config(api_key='', max_steps=0).validate()"` → 输出 `model: deepseek-chat | sessions_dir: data\sessions | max_steps: 8` 且成功拦截 `ConfigError: AGENT_MAX_STEPS 必须 >= 1`
  - 第 3 步：`python check_env.py` + `load_config()` + `LLM(cfg)` 联调 → `check_env.py` 输出正常；`get_type_hints(LLM.request)` 为 `{'messages': list[dict], 'tools': list | None}`；输出 `model: deepseek-flash | temp: 0.3 | timeout: 60.0`；`git status -s` 未追踪 `.env`
- **掌握情况与踩坑记录**：
  - 第 1 步手敲时曾将 `.strip()` 误敲为 `,strip()` 引发 `NameError`，并将 `_env_int` 与 `_env_float` 写串；
  - 第 3 步曾误将配置与真实 API Key 写入受 Git 追踪的 `.env.example`（已及时撤回并新建本地 `.env`），以及在 `agent/llm.py` 手敲出 `message:list[dist]` 拼写误差（已借助 `from __future__ import annotations` 差异认知与 `get_type_hints` 排查修正），也实践了 `.env` 拼写排查（`deepseek-falsh` → `deepseek-flash`）。现已完整掌握强类型配置、环境变量隔离与客户端参数透传。

## 9.2 完整消息协议模型
- **状态**：⏳ 待开始（准备进行第 1 步）
- **预习知识点导览**（完成后补充实操细节与踩坑记录）：
  - **协议完整表达（`ToolCallItem` / `tool_call_id` / `reasoning_content`）**：让工具调用轨迹从临时局部变量升级为一等公民对象，支持完整持久化与推理模型思考过程回传。
  - **双序列化隔离（`to_dict()` vs `to_record()`）**：发给大模型 API 时严格裁剪掉 `name`、`created_at`、`metadata` 等观测字段；落盘时完整保留元数据，兼顾协议合规与可审计性。
  - **向后兼容反序列化（`from_record()`）**：兼容读取阶段 4 旧版 `memory.json`（仅含 `role` / `content`）与新版完整记录，平滑升级不丢历史数据。
- **改动文件**：`agent/message.py`（待手敲）
- **验收命令与结果**：
- **掌握情况与踩坑记录**：

## 9.3 AST 安全计算器
- **状态**：⬜ 待开始
- **预习知识点导览**（完成后补充实操细节与踩坑记录）：
  - **为何禁用 `eval()`**：即使传入 `{"__builtins__": None}`，Python 仍可通过 `__class__.__mro__` 等属性链完成沙箱逃逸并执行任意系统命令。
  - **AST 白名单语法树求值（`ast.parse`）**：把表达式解析成抽象语法树，仅放行常量数字、四则/幂/取模运算符与白名单数学函数，从语法层彻底阻断属性访问、下标与函数注入。
  - **DoS 资源耗尽防护**：限制表达式最大长度、幂运算底数/指数上限与中间结果规模（防 `9**99999` 卡死进程），并移除旧版 `except` 后的不可达死代码。
- **改动文件**：`agent/tools/builtin.py`（待手敲）
- **验收命令与结果**：
- **掌握情况与踩坑记录**：

## 9.4 声明式工具注册表与异步并发执行器
- **状态**：⬜ 待开始
- **预习知识点导览**（完成后补充实操细节与踩坑记录）：
  - **声明式 Schema 自动推导（`@registry.tool` + `inspect` + `pydantic.create_model`）**：从函数类型注解与文档字符串自动生成 OpenAI Function Calling JSON Schema，消除“改了函数参数却忘改手写 JSON”的割裂问题。
  - **依赖注入与权限边界（`ToolContext` / `RiskLevel`）**：框架自动剥离 `ctx: ToolContext` 参数（不暴露给模型），由运行时注入工作目录、配置等上下文；通过 `RiskLevel`（只读/写入/高危）为阶段 11 的人工审批铺路。
  - **异步并发控制与自愈回填（`Semaphore` + `wait_for` + `gather`）**：单步多工具并行执行并限制最大并发与单工具超时；遇到参数校验失败时把 `[参数校验失败]` 错误作为工具结果回填给模型，引导模型自行纠偏重试。
  - **路径穿越防护**：文件类工具将目标路径 `resolve()` 后校验是否在 `workspace_dir` 沙箱内，拦截 `../` 越界读写。
- **改动文件**：`agent/tools/__init__.py`、`agent/tools/base.py`、`agent/tools/executor.py`、`agent/tools/builtin.py`（待手敲）
- **验收命令与结果**：
- **掌握情况与踩坑记录**：

## 9.5 全链路 Trace 与结构化日志
- **状态**：⬜ 待开始
- **预习知识点导览**（完成后补充实操细节与踩坑记录）：
  - **异步上下文透传（`contextvars`）**：在 `async/await` 并发协程间无侵入自动传递当前 `Trace` 与父子 `Span`，无需在每个业务函数签名里层层手传 `trace_id`。
  - **可观测指标采集（TTFT / Token `usage` / 耗时分布）**：记录首字延迟（TTFT）、各轮推理与工具调用的层级树，并将完整轨迹落盘为 `.jsonl`。
  - **结构化日志注入与可视化（`TraceContextFilter` + ASCII 瀑布图）**：让每条标准 `logging` 自动携带 `trace_id` / `span_id`，并通过 `python -m agent.observability.view` 在终端直观画出耗时瀑布图。
- **改动文件**：`agent/observability/__init__.py`、`agent/observability/tracer.py`、`agent/observability/logger.py`、`agent/observability/view.py`（待手敲）
- **验收命令与结果**：
- **掌握情况与踩坑记录**：
