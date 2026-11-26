# 阶段 10 学习记录：AsyncLLM 流式聚合与 L1 / L2 / L3 分层记忆

- **目标**：将同步阻塞的 `agent/llm.py` 升级为支持流式吐字、分片 `tool_calls` 聚合、指数退避重试与备用模型降级的 `AsyncLLM`；构建 Token 预算对齐窗口（L1）、乐观锁异步滚动摘要（L2）与按用户隔离的 BM25 跨会话长期记忆（L3）。
- **阶段状态**：✅ 已完成（**10.1 ～ 10.4** 全部验收通过，异步流式 LLM 与 L1/L2/L3 分层记忆全面闭环）

---

## 环节进度

| 环节 | 主题 | 状态 | 提交 Hash |
| :---: | :--- | :---: | :--- |
| 10.1 | AsyncLLM 流式聚合与重试降级 | ✅ 已完成 | `b6c5b60` |
| 10.2 | L1 Token 预算窗口与原子存储 | ✅ 已完成 | `44c089a` |
| 10.3 | L2 异步滚动摘要 | ✅ 已完成 | `c98dbc4` |
| 10.4 | L3 跨会话长期记忆（BM25） | ✅ 已完成 | `study(stage-10.4)` |

---

## 10.1 AsyncLLM 流式聚合与重试降级
- **状态**：✅ 已完成（第 1～5 步全部验收通过）
- **改动文件**：`agent/llm/__init__.py`、`agent/llm/provider.py`（并移除旧单文件 `agent/llm.py`）
- **学习知识点详解（第 1～5 步全览）**：
  1. **只重试临时故障 & 领域异常与协议插座（`RETRYABLE_ERRORS` / `LLMError` / `LLMClient`）**：
     - 仅对 `APITimeoutError`、`APIConnectionError`、`RateLimitError`、`InternalServerError` 四类临时故障重试，对 `400/401` 确定性错误立刻暴露；
     - 用 `LLMClient(Protocol)` 留好“假大脑插座”，离线单测与冷链 40 条考卷评测可直接注入假模型零成本秒跑；
     - `_usage_to_dict()` 兼容 Pydantic 响应与普通字典，过滤嵌套明细与 `bool` 子类只留可累加数值。
  2. **接管重试、指数退避与主备切换（`AsyncLLM.__init__` / `_models` / `_backoff` / `complete`）**：
     - 显式设 `AsyncOpenAI(..., max_retries=0)` 关掉 SDK 黑盒重试，由外层统一记录每次重试 Span 并在主模型重试耗尽后无缝切换 `fallback_model`；
     - `_backoff()` 使用指数退避（`0.5s → 1s → 2s ...` 上限 `8s`）+ 随机抖动 `random.uniform(0, 0.25)` 防止高并发雪崩，且放在 `with span(...)` 外面保持每次尝试耗时真实；
     - `complete()` 面向 L2 滚动摘要、评测裁判等后台非流式任务，并自动调用 `trace.add_usage(usage)` 记账。
  3. **流式分片拼图器（`_StreamAggregator`）与 TTFT 首字延迟**：
     - 先判断 `chunk.usage` 再判断 `if not chunk.choices:`，捕住开启 `stream_options={"include_usage": True}` 后的流尾 Token 账单；
     - 仅在首次收到思考/正文/工具增量时记录 `first_token_at` 计算 `ttft_ms`，并写入阶段 9 的 `Span` 直接在瀑布图高亮；
     - 工具调用碎片按 `tc.index` 分槽缓冲（支持单步并发调多工具，如冷链并行查 OMS/WMS/TMS），`id` 有值才写、`name`/`arguments` 用 `+=` 拼接，流结束在 `finalize()` 按索引排序生成 `ToolCallItem`（缺 `id` 时兜底生成唯一 ID）与完整 `Message`。
  4. **流式防重红线（`stream_chat` 与 `emitted` 守卫）**：
     - `emitted == False`（尚未向用户吐出任何字）：安全重试或切换备胎模型，用户无感；
     - `emitted == True`（已吐出半句话后中途断网）：禁止静默重试拼接残句，立刻 `raise LLMError("流式输出中断: ...") from exc`。
  5. **包门面导出与旧文件退役**：
     - 在 `agent/llm/__init__.py` 统一导出 `AsyncLLM` / `LLMClient` / `LLMError` / `LLMEvent`，正式删除旧同步 `agent/llm.py`。
- **验收命令与结果**：
  - 第 1 步：`RETRYABLE_ERRORS` 数量为 `4`，`LLMEvent` 实例化正常，`_usage_to_dict` 过滤掉 `cache_hit: True` 与嵌套 `details` 仅保留 `{'prompt_tokens': 120, 'completion_tokens': 30}`
  - 第 2 步：`complete()` 离线模拟主模型连炸 2 次超时 → 自动降级成功，输出 `text: 降级成功 | calls: ['primary', 'primary', 'backup']` 与 3 个 Span 状态 `[('primary', 1, 'error'), ('primary', 2, 'error'), ('backup', 1, 'ok')]`
  - 第 3 步：`_StreamAggregator.feed()` 喂入 5 片碎片 → 正确输出 `reasoning_delta` / `content_delta`，`cal`+`culator` 与切分 JSON 精确拼合，`usage` 与 `finish_reason` 完整捕获
  - 第 4 步：`_stream_once()` + `finalize()` 实测 → 输出 `types: ['reasoning_delta', 'content_delta', 'message_complete']`、`span_ttft_ok: True | tokens: 12`
  - 第 5 步（10.1 总验收）：通过 `from agent.llm import AsyncLLM, LLMError` 验证 → `1_assemble: calculator {"expression": "1+2"}`、`2_fallback: 备胎顶上 | calls: ['primary', 'primary', 'backup']`、`3_midstream_no_retry: LLMError True`；旧 `agent/llm.py` 已移除
- **掌握情况与踩坑记录**：第 1 步因编辑器“折叠单子目录（Compact Folders）”功能误将 `__init__.py` 建在了 `agent/llm/__pycache__/` 内，触发了旧 `agent/llm.py` 遮蔽报 `'agent.llm' is not a package`；移回 `agent/llm/__init__.py` 后立即通过，第 2～5 步全部一次性零报错跑通！下一步进入 **10.2 L1 Token 预算窗口与原子存储**。

## 10.2 L1 Token 预算窗口与原子存储
- **状态**：✅ 已完成（第 1～8 步全部验收通过，已退役旧单文件 `agent/memory.py`）
- **改动文件**：`agent/llm/token_counter.py`、`agent/llm/__init__.py`、`agent/state.py`、`agent/memory/__init__.py`、`agent/memory/store.py`、`agent/memory/window.py`（并移除旧单文件 `agent/memory.py`）
- **学习知识点详解（第 1～8 步全览）**：
  1. **Token 估算器（`agent/llm/token_counter.py`）**：`@lru_cache(maxsize=1)` 懒加载 `tiktoken`，未安装时自动降级为中英文字符启发式估算（CJK × 0.6 + 其他 × 0.3 + 1），叠加每条消息固定开销与 `tool_calls` / `reasoning_content` 计费。
  2. **会话检查点模型（`agent/state.py`）**：`RunStatus`（`IDLE` / `WAITING_APPROVAL`）、`PendingApproval` 与 `SessionState` 双向序列化（`to_record` / `from_record`），天然支持高危审批挂起与重启续关。
  3. **防穿越存储协议、内存存储与旧版迁移（`agent/memory/store.py` 上半）**：`_SESSION_ID_RE` 正则拦截 `../etc/passwd` 抛出 `InvalidSessionId`；`SessionStore(Protocol)` 留好换库插座；`InMemorySessionStore` 用 `json.loads(json.dumps(raw))` 深拷贝隔离外部篡改；`load_legacy_messages()` 过滤旧版 `memory.json` 中的 `SYSTEM` 消息。
  4. **原子落盘与异步线程池卸载（`agent/memory/store.py` 下半 `JsonFileSessionStore`）**：同目录 `tempfile.mkstemp(dir=path.parent, suffix=".tmp")` + `os.fdopen(fd, ...)` + `os.replace(tmp, path)` 防写一半崩溃损坏存档，`except BaseException` 清理 `.tmp` 残片；`load/save/delete` 经 `asyncio.to_thread` 卸载避免阻塞事件循环，`list_ids()` 用 `glob("*.json")` + `p.stem` 过滤草稿并排序。
  5. **协议外科医生与轮次边界窗口（`agent/memory/window.py`）**：`turn_starts()` 以 `USER` 下标为界（兜底含 `0`）；`sanitize()` 维护待核销小票篮 `open_ids` 与内部闭包 `close_open()`，丢弃 `SYSTEM` 与孤儿 `tool`、自动为缺失回执补齐 `MISSING_TOOL_RESULT`；`ContextWindowBuilder.select()` 用 `zip(starts, starts[1:] + [len(messages)])` 错位拉链切轮次、`reversed(bounds)` 倒序装车，并通过 `start < len(messages)` 保证最新一轮始终保留。
  6. **包门面统一导出**：在 `agent/llm/__init__.py` 补导出 Token 估算三函数，在 `agent/memory/__init__.py` 导出 L1 全家桶与 `__all__`。
- **验收命令与结果**：
  - 第 1 步：`has_tiktoken: False`、`empty: 0 | cn: 5 | en: 5`、`m1: 12 | m2_with_tool: 19 | total: 31`
  - 第 2～3 步：`version: 2 | status: WAITING_APPROVAL | pending_ids: ['c_pay']`、`roundtrip_ok: True`
  - 第 4 步：`blocked: True | isolated: True | ids: ['case_001'] | deleted: True`、`legacy_roles: ['user']`
  - 第 5a 步：`files: ['cold_001.json'] | content: 零下18度告警 | missing: None | blocked: True`
  - 第 5b 步：`empty_ids: []`、`ids1: ['a_case', 'b_case'] | msg: 压缩机停机`、`del: (True, False) | ids2: ['b_case']`
  - 第 6 步：`starts: [0, 1, 3]`、`clean_seq: [('user', '冷柜坏了'), ('assistant', None), ('tool', 'c1'), ('tool', 'c2'), ('user', '怎么卡住了')]`、`patched_c2: True`
  - 第 7 步（30 轮含工具裁剪）：`trimmed: True | first_role: user | paired: True | tokens<=250: True`、`kept_turns: 5 | tiny_keeps_last_turn: True`
  - 第 8 步（端到端联合验收）：`legacy_removed: True`、`status: WAITING_APPROVAL | pending: ['c_pay']`、`window_roles: ['user', 'assistant', 'tool', 'user', 'assistant', 'tool'] | tokens: 60`
- **掌握情况与踩坑记录**：第 4 步因 IDE 折叠目录曾误建在 `agent/memory/__pycache__/` 内，移回 `agent/memory/` 后第 4～8 步全部一次性零笔误通过！本节还正式沉淀了“全局定位上下游图 + 互动图解 + 文本图解 + 大白话逐方法精讲”的黄金教学节奏。下一步正式进入 **10.3 L2 异步滚动摘要**。

## 10.3 L2 异步滚动摘要
- **状态**：✅ 已完成（全部模块一次性零失误验收通过，耗时约 33 分钟：`2026-11-26 14:53 ~ 15:26`）
- **改动文件**：`agent/memory/summarizer.py`、`agent/memory/manager.py`、`agent/memory/__init__.py`
- **学习知识点详解**：
  1. **紧凑剧本转换与滚雪球压缩（`agent/memory/summarizer.py`）**：
     - `render_transcript(messages, tool_preview=200)` 将多角色消息（含 `tool_calls` 与 `content` 并列共存的 `ASSISTANT` 消息）摊平为省 Token 纯文本剧本，`TOOL` 名称缺省回退 `tool_call_id` 并截断前 200 字防巨型工具返回撑爆请求；
     - `Summarizer.summarize()` 复用 10.1 `LLMClient.complete(..., temperature=0.1)` 低温合并“已有摘要 + 新增对话”，并通过 `text[: self.max_chars * 2]` 代码级硬截断防止模型输出失控膨胀。
  2. **记忆门面与单会话隔离并发（`agent/memory/manager.py`）**：
     - `MemoryManager` 统一编排 L1 存储/滑窗、L2 摘要与 10.4 L3 长期记忆插座；
     - `lock(session_id)` 按会话隔离互斥锁（不同会话并行不阻塞），`_tasks: set[asyncio.Task]` 强引用后台摘要任务并配合 `add_done_callback(self._tasks.discard)` 防 GC 误杀与内存泄漏；
     - `build_context()` 按顺序把 L2 摘要与 L3 长期记忆拼入 `system_text`，先算 `reserved = count_text_tokens(system_text) + 4` 再让 L1 滑窗填满剩余预算，并打上 `span("memory", "build_context")` 追踪埋点。
  3. **双向乐观锁防并发覆盖**：
     - **防线 A（`commit()`）**：前台提交前加锁重读磁盘 `stored`，若同场会话（`created_at` 相同）且磁盘摘要更超前（`stored.summarized_upto > state.summarized_upto`），先抄回新摘要再存盘，防止旧快照拍空后台新摘要；
     - **防线 B（`summarize_if_needed()`）**：在锁外异步调摘要模型（不阻塞前台聊天），算完后再加锁重读 `fresh` 做四重校验（非空、`created_at` 未变、`summarized_upto` 未变、`len(fresh.messages) >= end`），彻底拦截 `/reset` 或同 ID 重建会话引发的僵尸摘要污染。
- **验收命令与结果**：
  - `summarizer.py`（剧本转换 + 滚雪球压缩）：8 行剧本与截断输出全达标；假模型实测 `r1: '- F01超温40m'`、`temp: 0.1 | has_wu: True`、`has_old: True | clipped_len: 20`；
  - `manager.py`（异步摘要 + System 注入 + 防线 A）：`1_summary: 汇总:F01冷柜超温40分钟 | upto: 10`、`2_injected: True`、`3_guard_commit: True`、`4_clear_guard: True | after_clear_updated: False`；
  - 10.3 端到端总验收（顶层导出 + Trace 穿透 + 防线 B 同 ID 重建拦截）：`1_trace_spans: [('memory', 'summarize'), ('memory', 'build_context')] | ok1: True`、`2_bundle_has_summary: True`、`3_race_blocked: True`。
- **掌握情况与踩坑记录**：业务代码全程零笔误一把过！过程中顺带排查出新开 PowerShell 下 `python` 被 WindowsApps 商店空壳截胡（改用 `py` 直连 `Python313`，且发现本机已安装 `tiktoken`），以及复习了 Python 分号后不可接复合语句（`async def`）的语法细节。从本节起升级为“按完整内聚模块推进”的更流畅节奏。下一步直接进入 **10.4 L3 跨会话长期记忆（BM25）**。

## 10.4 L3 跨会话长期记忆（BM25）
- **状态**：✅ 已完成（全链路联调验收通过，耗时约 40 分钟：`2026-11-26 15:26 ~ 16:06`，阶段 10 圆满收官）
- **改动文件**：`agent/memory/long_term.py`、`agent/tools/builtin.py`、`agent/memory/manager.py`、`agent/memory/__init__.py`
- **学习知识点详解**：
  1. **零依赖中英文分词与 Okapi BM25 检索（`agent/memory/long_term.py`）**：
     - `tokenize()` 将英文/数字按小写整词切分，连续汉字同时切出**单字（保底召回）+ 二元组 Bigram（锁准词义）**，零第三方分词/向量库依赖实现精准中文匹配；
     - `LongTermMemory` 按 `user_id` 隔离事实库，使用 `threading.Lock` 保护跨线程并发（适配同步工具在 `asyncio.to_thread` 线程池中运行），通过 `.tmp` + `replace()` 原子落盘，并在 `add()` 中做精确去重；
     - `search()` 当用户事实数 `<= top_k` 时直接全返回避免漏记，否则计算 BM25+（`k1=1.5` 控制词频饱和、`b=0.75` 控制长度归一化、`math.log(1 + ...)` 保证 IDF 非负）并按 `(-score, idx)` 稳定排序返回 Top-K。
  2. **两条腿走路与 `ToolContext` 权限隔离（`agent/tools/builtin.py`、`agent/memory/manager.py`）**：
     - 被动自动注入：`MemoryManager.build_context()` 正式以强类型 `LongTermMemory` 接入 L3，每轮自动召回 Top-3 事实挂载到 `【关于该用户的长期记忆】`；
     - 主动记忆工具：注册 `remember_fact`（`RiskLevel.WRITE`，`fact` 上限 300 字）与 `recall_facts`（`RiskLevel.READ_ONLY`，`top_k=5`），通过 `ctx: ToolContext` 隐式注入 `ctx.user_id` 与 `ctx.long_term`，对大模型隐藏身份字段，彻底杜绝跨用户越权读写。
- **验收命令与结果**：
  - `long_term.py` 独立验收：`1_tokens: ['python313', '冷', '链', '冷链']`、`2_dedup: True False | total_u1: 5`、`3_top2: ['冷柜超温30分钟按条款3.2定责', '门店A01位于郑州常用F01冷柜']`、`4_isolated: ['别人家的机密偏好'] | u3: []`；
  - 阶段 10 大收官联调验收：`1_schema_hides_ctx: ['fact'] ['query']`、`2_remember: 已记住 | 该事实已存在，无需重复记忆`、`3_cross_session_inject: True | facts: ['门店A01使用F01冷柜且偏好晚上配送']`、`4_recall_same_user: - 门店A01使用F01冷柜且偏好晚上配送`、`5_user_isolated: 没有相关记忆 | other_facts: []`。
- **掌握情况与踩坑记录**：`long_term.py` 149 行一次性零错误通过；接入 `builtin.py` 时误把 `remember_fact` 插在原 `write_workspace_file` 的 `@registry.tool(HIGH_RISK)` 装饰器下方导致重复注册，触发了 9.4 自研的 `ValueError: 工具 'remember_fact' 重复注册` 防呆校验，挪回装饰器位置后秒过！阶段 10 全线通关，下一步开启 **阶段 11：异步流式 ReAct 状态机、HITL 人工审批与 FastAPI SSE**。
