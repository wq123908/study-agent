# 阶段 9 学习记录：基线修复、声明式安全工具层与全链路 Trace 底座

- **目标**：修复第 8 阶段代码里的基线缺陷，将工具层重构为自动生成 Schema + Pydantic 校验 + AST 安全计算 + 并发超时控制，并建立可观测 Trace 底座。
- **阶段状态**：✅ 已完成（**9.1 ～ 9.5** 全部验收通过，全链路联调达标）

---

## 环节进度

| 环节 | 主题 | 状态 | 提交 Hash |
| :---: | :--- | :---: | :--- |
| 9.1 | 基线止血与强类型配置 | ✅ 已完成 | `f40398e` / `7f67b7c` |
| 9.2 | 完整消息协议模型（`ToolCallItem` / 双序列化） | ✅ 已完成 | `22c684c` |
| 9.3 | AST 安全计算器（替代 `eval`） | ✅ 已完成 | `5d1c13e` |
| 9.4 | 声明式工具注册表与异步并发执行器 | ✅ 已完成 | `8522fc9` / `2f85449` / `a566e9d` / `3bf36d0` / `c839fee` |
| 9.5 | 全链路 `Trace → Span` 与结构化日志 | ✅ 已完成 | `7893fdf` / `71d9eb1` / `00f5bfc` / `study(stage-9.5)` |

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
- **状态**：✅ 已完成（第 1～2 步全部验收通过）
- **改动文件**：`agent/message.py`
- **学习知识点详解**：
  1. **完整协议角色与 `ToolCallItem` 结构化模型**：
     - 补齐第四种协议角色常量 `TOOL = "tool"`，消除业务代码里的 `"tool"` 硬编码字符串。
     - 定义 `ToolCallItem(id, name, arguments)` 表达大模型发起的每一次工具调用，其中 `arguments` 保留模型返回的原始 JSON 字符串；并通过 `to_openai_dict()` / `from_openai_dict()` 兼容嵌套 `{"function": {...}}` 与扁平字典两种输入形式。
  2. **消息生命周期元数据字段与可变默认值隔离**：
     - 扩展 `Message` 支持 `content: str | None = None`、`tool_calls: list[ToolCallItem]`、`tool_call_id`、`name`、`reasoning_content`、`created_at` 与 `metadata`。
     - `tool_calls` 与 `metadata` 使用 `field(default_factory=...)` 防共享；`created_at` 使用 `field(default_factory=time.time)`（传入函数引用而非立即调用 `time.time()`），为每条消息自动记录精确创建时间戳。
  3. **双序列化隔离（`to_dict()` 发 API vs `to_record()` 落盘）**：
     - **`to_dict()`（做减法，严守 API 协议）**：当 `content` 为 `None`（常见于工具调用消息）时按协议转成 `""`；仅在 `assistant` 且存在 `tool_calls` 时附带 `tool_calls`（以及部分推理模型要求同一工具轮次回传的 `reasoning_content`）；仅在 `tool` 消息时附带 `tool_call_id`；严格过滤掉 `name`、`created_at`、`metadata` 等内部观测字段，避免模型接口报错。
     - **`to_record()`（做加法，保留完整现场）**：原样保留 `content`（不把 `None` 强转为 `""`），并持久化 `name`（记录工具名称）、`created_at`（供后续 L2 摘要与时间排序使用）、`reasoning_content` 与 `metadata`；仅写入非空可选字段，保持 JSON 简洁可读。
  4. **向后兼容反序列化（`from_record()`）**：
     - 阶段 4 遗留的 `memory.json` 每条只有 `role` 和 `content`。使用 `raw.get("tool_calls") or []`、`raw.get("created_at") or time.time()`、`raw.get("metadata") or {}`，同时防御“键不存在”与“键值为 JSON `null`（`None`）”两种边界情况，防止列表推导式遍历 `None` 报错。
  5. **类体内前向引用与 `from __future__ import annotations`（实操印证）**：
     - 在 `class ToolCallItem:` 尚未执行完类体时，内部方法 `@classmethod def from_openai_dict(...) -> ToolCallItem:` 若无首行 `from __future__ import annotations` 开启注解延迟求值，会在导入阶段直接抛出 `NameError: name 'ToolCallItem' is not defined`。
- **验收命令与结果**：
  - 第 1 步：`python -c "import json; from agent.message import ASSISTANT, TOOL, ToolCallItem, Message; ..."` → 输出 `assistant(tool_calls)` 标准 JSON（含 `reasoning_content`）、`{"role": "tool", "content": "3", "tool_call_id": "call_1"}`（无观测字段）与 `[assistant] -> calculator({"expression": "1+2"})`
  - 第 2 步：`python -c "import json; from agent.message import ASSISTANT, TOOL, USER, ToolCallItem, Message; ..."` → 输出 `record_keys: ['content', 'created_at', 'metadata', 'reasoning_content', 'role', 'tool_calls']`、`roundtrip_ok: True`、`legacy_ok: True`、`tool_record_has_name: calculator`
- **掌握情况与踩坑记录**：
  - 第 1 步手敲时漏写首行 `from __future__ import annotations` 导致 `ToolCallItem.from_openai_dict` 返回值注解触发 `NameError`（正好与 9.1 “延迟注解掩盖拼写错误”形成一正一反印证）；
  - 同轮还将 `TOOL` 常量误拼成 `TOOLS`，并漏写了 `reasoning_content` 与 `metadata` 两个字段；通过报错定位与逐行对照修正后已完整掌握消息双序列化与旧版数据兼容设计。

## 9.3 AST 安全计算器
- **状态**：✅ 已完成（第 1～2 步全部验收通过）
- **改动文件**：`agent/tools/__init__.py`、`agent/tools/builtin.py`
- **学习知识点详解**：
  1. **为何 `eval(..., {"__builtins__": None})` 依然可被逃逸**：
     - Python 一切皆对象，清空 `__builtins__` 后仍可通过 `(1).__class__.__base__.__subclasses__()` 顺着继承链捞出系统类并执行任意代码；同时 `9**99999` 会直接引发算力/内存 DoS。
  2. **AST 白名单语法树求值（`ast.parse(..., mode="eval")` + `_eval_node`）**：
     - `ast.parse(..., mode="eval")` **只做词法与语法解析、绝不执行代码**，且限制只能输入单个表达式（禁止 `import`、赋值、多语句）。
     - 递归节点 `_eval_node` 采用**严格白名单**：只放行合法数字常量、`pi/e` 常量名、`_UNARY_OPS` 一元运算符、`_BIN_OPS` 二元运算符以及 `_FUNCS` 数学函数直接调用（`isinstance(node.func, ast.Name)` 且 `not node.keywords`），彻底阻断 `ast.Attribute` 属性链访问与 `__import__` 等未知调用。
  3. **`type(node.value) in (int, float)` 与 `isinstance` 的细微陷阱**：
     - Python 中 `bool` 是 `int` 的子类（`isinstance(True, int) == True`）。刻意用精确类型检查 `type(node.value) in (int, float)`，能同时拒绝 `True + 1` 这类布尔隐式数值运算。
  4. **前置 DoS 算力与溢出防线**：
     - 限制表达式最大长度 `MAX_EXPRESSION_LEN = 200`；
     - 在真正执行 `operator.pow` **之前**拦截 `abs(right) > MAX_EXPONENT`（`1000`），防止 `9**99999` 卡死进程；
     - 运算后检查 `abs(result) > MAX_ABS_RESULT`（`10**100`），并兼容替换大模型常输出的中文符号（`×` → `*`、`÷` → `/`、`^` → `**`）。
  5. **数值格式化 `_format_number` 与工具错误自愈封装 `calculator`**：
     - `value.is_integer() and abs(value) < 1e15` 把整除产生的 `21.0` 清洗成 `"21"`，同时避免超大浮点数强转 `int` 丢失科学计数精度；
     - `f"{value:.10g}"` 保留 10 位有效数字并自动去掉尾零，消去 `0.1 + 0.2 -> 0.30000000000000004` 的 IEEE 754 尾数噪音；
     - `calculator()` 捕获 `ZeroDivisionError`、`ValueError`、`SyntaxError`、`TypeError`、`OverflowError` 并返回可读提示字符串，引导大模型在下一轮自我纠偏，替代旧版 `agent/tools.py` 的 `eval` 与死代码。
  6. **Python 包约定与同名文件遮蔽规则（实操印证）**：
     - 只有包含 **`__init__.py`**（前后双下划线）的目录才会被 Python 识别为常规包；普通文件名 `init.py` 不具备该语义。
     - 当目录下同时存在 `agent/tools.py` 与 `agent/tools/` 子目录时，若缺失 `agent/tools/__init__.py`，Python 会优先加载 `agent/tools.py` 从而抛出 `ModuleNotFoundError: 'agent.tools' is not a package`。
- **验收命令与结果**：
  - 第 1 步：`safe_eval` 实测 `12*(3+4)=84`、`sqrt(16)+max(2,5)=9.0`、`6×7÷2=21.0`、`-5+2=-3`；成功拦截 `__import__(str(1))`（`不支持的语法: Call`）、`9**99999`（`指数超过 1000`）、`(1).__class__`（`不支持的语法: Attribute`）与 `True + 1`（`不支持的语法: Constant`）
  - 第 2 步：`calculator` 实测 `12*(3+4) => 84`、`6×7÷2 => 21`、`0.1+0.2 => 0.3`、`1/0 => 计算错误：除数不能为 0`、`1e300**2 => 计算错误：(34, 'Result too large')。请修正表达式后重试。`
- **掌握情况与踩坑记录**：
  - 第 1 步新建包入口时曾误命名为 `agent/tools/init.py`（漏掉双下划线），直接触发了 `'agent.tools' is not a package` 遮蔽报错；重命名为 `__init__.py` 后立即恢复正常。
  - 手敲 `builtin.py` 第 15 行时曾将 `_UNARY_OPS` 拼成 `_UNARY_POS`（且标注为两参 `Callable`），及时定位修正并用 `-5+2` 验证通过。现已完整掌握 AST 白名单沙箱求值与包结构组织原则。

## 9.4 声明式工具注册表与异步并发执行器
- **状态**：✅ 已完成（第 1～7 步全部验收通过）
- **已掌握知识点（第 1～6 步）**：
  - `RiskLevel(str, Enum)` 三级权限分级（`READ_ONLY` / `WRITE` / `HIGH_RISK`）与 JSON 兼容；
  - `ToolContext` 运行时上下文设计与 `if TYPE_CHECKING:` 防前向/循环导入；
  - `_StrictArgs`（`ConfigDict(extra="forbid")`）拒绝模型传未定义参数，并清理 Schema 冗余 `title`；
  - `ToolSpec.is_async`（`inspect.iscoroutinefunction`）区分同步与协程工具；
  - `@registry.tool` 装饰器 + `get_type_hints(func, include_extras=True)` 保留 `Annotated[..., Field(...)]` 元数据 + 自动剥离 `ToolContext` 参数 + `Ellipsis` 标记必填参数并由 `pydantic.create_model` 自动推导 Schema；
  - `ToolResult` 统一执行结果结构（`ok` / `error_type` / `duration_ms`）、`asyncio.Semaphore(max_concurrency)` 并发限流阀门、`_truncate` 输出长度防爆截断与 `FaultInjector` 故障注入钩子；
  - `_run()` 四层保护（JSON + Pydantic 校验失败回填 `[参数校验失败]` 引导模型自愈、`ToolContext` 在校验后注入、同步函数通过 `asyncio.to_thread` 防阻塞事件循环、`asyncio.wait_for` 超时熔断与 `logger.exception` 记录堆栈同时隔离内部异常）；
  - `execute_one()`（`time.perf_counter()` 计时、统一 `finish` 截断出口、未知工具列出可用工具名）与 `execute_batch()`（`asyncio.gather` 并发执行并严格保序）；
  - `register_builtin_tools` 装饰器集中注册（`name="calculator"` 复用 9.3 安全计算器、`now.astimezone()` 带时区本地时间）、`write_workspace_file` 标为 `HIGH_RISK` 并实现“正则白名单 + `Path.resolve()` 父目录核对”双层沙箱防路径穿越；
  - **包门面统一导出（`agent/tools/__init__.py`）**：提供 `default_registry()` 工厂方法（每次创建独立实例避免全局状态污染）与 `__all__` 清晰边界，正式退役阶段 5 单文件 `agent/tools.py`。
- **改动文件**：`agent/tools/__init__.py`、`agent/tools/base.py`、`agent/tools/executor.py`、`agent/tools/builtin.py`（并移除旧 `agent/tools.py`）
- **验收命令与结果**：
  - 第 1 步：`ToolSpec.to_openai_schema()` 正常输出含 `"additionalProperties": false` 且无 `title` 的 Schema，`is_async: True`，`_StrictArgs` 传入未知字段触发 `ValidationError`
  - 第 2 步：`@reg.tool(risk_level=RiskLevel.WRITE, timeout=5)` 注册 `save_note(..., ctx: ToolContext, count: int = 1)` → 输出 `names: ['save_note'] | len: 1 | has_save_note: True`、`ctx_param: ctx`，导出 Schema 中仅保留 `title`（`maxLength: 20`）与 `count`（`default: 1`），`ctx` 已自动剔除
  - 第 3 步：`ToolExecutor(reg, max_output_chars=10)` 验收 → 输出 `is_high_risk: True | unknown: None` 与 `truncate: '0123456789\n[输出过长，已截断 6 个字符]'`
  - 第 4 步：`_run()` 四场景实测 → `add('3', 4)` 输出 `ok: True | content: alice:7`、`add('bad', 1)` 返回 `invalid_arguments`、`slow` 超时返回 `timeout`、`boom` 捕获 `RuntimeError` 返回 `exception`（`logger.exception` 打印堆栈但不崩溃）
  - 第 5 步：`execute_one` + `execute_batch` 实测 → `unknown: False unknown_tool`、4 个 0.3s 异步工具并发 `batch_elapsed: 0.316` 秒（`< 0.9s`）且保序 `['c0', 'c1', 'c2', 'c3']`、`fault_injector` 注入 `TimeoutError` 返回 `fault: False timeout`
  - 第 6 步：`register_builtin_tools` 实测 → 注册 `['get_current_time', 'calculator', 'write_workspace_file']`、`high_risk_write: True`、`12*(3+4)` 返回 `84`、`../evil.txt` 被拦截且未写磁盘、合法 `note.md` 写入成功
  - 第 7 步（9.4 总验收）：从 `agent.tools` 门面导出运行 → `1_schema_no_ctx: True`、`2_bad_arg: False invalid_arguments True`、`3_concurrent_lt_0.9: True | elapsed: 0.302`、`4_sandbox: True | evil_exists: False`；旧 `agent/tools.py` 已移除
- **掌握情况与踩坑记录**：第 1～7 步全部一次性验收通过！第 4 步通过观察 `logger.exception` 堆栈理解了“日志记录堆栈”与“安全拦截返回”的区别；第 6 步顺利实现工具注册与双层沙箱防穿越；约定了“多参数一行一个”排版风格后手敲准确度大幅提升（注：`base.py` 头部留有旧导入、`__init__.py` 首行留有旧文档字符串，均不影响运行）。下一步进入阶段 9 最后一节 **9.5 全链路 Trace 与结构化日志**。

## 9.5 全链路 Trace 与结构化日志
- **状态**：✅ 已完成（第 1～9 步全部验收通过）
- **改动文件**：`agent/observability/__init__.py`、`agent/observability/tracer.py`、`agent/observability/logger.py`、`agent/observability/view.py`、`agent/tools/executor.py`
- **学习知识点详解（第 1～9 步全览）**：
  1. **协程隔离透传（`contextvars.ContextVar`）**：
     - 替代普通全局变量防多协程并发串台；通过 `activate_trace` / `deactivate_trace` 管理请求生命周期，`@contextmanager def span(...)` 借由 `set()` / `reset(token)` 自动构建任意深度的父子 `parent_id` 调用树。
     - 区分 `GeneratorExit`（SSE 断流）为 `status="cancelled"` 而非报错；捕获异上下文关闭的 `ValueError` 安全兜底；无活动 Trace 时零侵入退化为空操作。
  2. **线程安全聚合模型（`Span` / `Trace`）**：
     - `Span.to_dict()` 手动补充 `@property duration_ms`（因 `asdict()` 不导出属性）；
     - `Trace` 使用 `threading.Lock`（`repr=False, compare=False`）同时兼容主事件循环协程与 `to_thread` 工作线程写入，手写 `to_dict()` 避开 `asdict()` 深拷贝锁报错；`add_usage()` 显式排除 `bool` 子类避免误计 Token。
  3. **面向协议的可插拔导出与容错隔离（`TraceExporter` / `JsonlTraceExporter` / `Tracer`）**：
     - `TraceExporter(Protocol)` 定义鸭子类型接口，按日加锁追加行式 `.jsonl`（`default=str` 兜底非 JSON 对象）；`InMemoryTraceExporter` 供离线测试断言；
     - `Tracer.finish_trace()` 以 `if trace.end is not None: return` 保障幂等不重复导出，用 `try/except` 隔离导出失败确保观测故障不拖垮业务。
  4. **结构化日志注入（`TraceContextFilter` + `JsonFormatter` + `setup_logging`）**：
     - Filter 必须挂在 **`handler.addFilter(...)`** 而非 `root` logger，确保所有子模块向上冒泡的日志均能自动注入 12 位 `trace_id` 与 `session_id`；
     - 支持文本与单行 JSON 双模式切换，使用 `root.handlers[:] = [handler]` 防重复打印并静音 `httpx`/`openai` 刷屏日志。
  5. **终端 ASCII 瀑布图与工具埋点联调（`view.py` + `executor.py`）**：
     - 按 `parent_id` 重建邻接表并按 `start` 排序，DFS 递归渲染缩进、相对偏移条与 `ttft_ms` / `✗ error` 高亮；`main(argv=None) -> int` 兼顾 CLI（`python -m agent.observability.view`）与单测可测性；
     - 在 `ToolExecutor.execute_one()` 接入 `with span("tool", ...)`，统一收敛未知工具、错参、超时与并发工具耗时，实现 9.1～9.5 全链路贯通。
- **验收命令与结果**：
  - 第 1 步：`Span` 实测 → `before_end: None | default_trace: None`、`after_end: 250.0 | status: error | err: timeout | attrs: {'ttft_ms': 120.5}`
  - 第 2 步：`Trace` 实测 → `usage: {'prompt_tokens': 150, 'completion_tokens': 35} | spans: 1 | ms: 500.0`（忽略 `cache_hit: True`）、`has_lock_in_repr: False`
  - 第 3 步：导出器实测 → 写出 `2026-11-22.jsonl` 且 `trace_id_match: True | input: demo.txt`、`mem_count: 1`
  - 第 4 步：`Tracer` 实测 → `BrokenExporter` 报 `OSError: 磁盘满了` 被隔离，重复 `finish_trace` 幂等，输出 `exported_count: 1 | output: hello | status: ok`
  - 第 5 步：`span` 嵌套实测 → `inside_tid: True`、`outside_tid: -`、`parent_link_ok: True`、`orphan_ok: - ok`
  - 第 6 步：`logger.py` 实测 → 文本日志自动区分 `-` 与 `aaeefad5b2b3`，JSON 模式输出含 `trace_id` / `session_id: "sess_42"` 的标准 JSON
  - 第 7～8 步：`view.py` 实测 → `python -m agent.observability.view --list 5` 输出 `cli_demo` 概览行，紧接着画出完整 `step-1` → `llm`（`ttft=18.5ms`）+ `tool` 瀑布图
  - 第 9 步（阶段 9 全链路总验收）：并发执行 `get_current_time`、`calculator`、`nope` → 3 条 `agent.tools.executor` 日志均自动带 `94e9c07a7986`，`python -m agent.observability.view` 展示并发重叠条（总耗时 10.1ms）及 `tool:nope ... ✗ unknown_tool` 错误高亮
- **掌握情况与踩坑记录**：第 3 步经“餐厅总账单与可插拔记账插座”类比后厘清了 `TraceExporter` 职责；第 5 步曾将 `current_trace`～`span` 多缩进 4 空格误放入 `class Tracer` 内导致 `ImportError`，用 `Shift+Tab` 修正后即通；第 6～9 步全部一次性通过验收！阶段 9 圆满收官，下一阶段进入 **阶段 10 —— AsyncLLM 流式聚合与 L1/L2/L3 分层记忆**。
