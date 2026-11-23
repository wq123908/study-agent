# 阶段 10 学习记录：AsyncLLM 流式聚合与 L1 / L2 / L3 分层记忆

- **目标**：将同步阻塞的 `agent/llm.py` 升级为支持流式吐字、分片 `tool_calls` 聚合、指数退避重试与备用模型降级的 `AsyncLLM`；构建 Token 预算对齐窗口（L1）、乐观锁异步滚动摘要（L2）与按用户隔离的 BM25 跨会话长期记忆（L3）。
- **阶段状态**：⏳ 进行中（已完成 **10.1**，准备开始 **10.2**）

---

## 环节进度

| 环节 | 主题 | 状态 | 提交 Hash |
| :---: | :--- | :---: | :--- |
| 10.1 | AsyncLLM 流式聚合与重试降级 | ✅ 已完成 | `study(stage-10.1)` |
| 10.2 | L1 Token 预算窗口与原子存储 | ⏳ 待开始 | - |
| 10.3 | L2 异步滚动摘要 | ⬜ 待开始 | - |
| 10.4 | L3 跨会话长期记忆（BM25） | ⬜ 待开始 | - |

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
- **状态**：⏳ 待开始（准备进行第 1 步）
- **预习知识点导览**（完成后补充实操细节与踩坑记录）：
  - **Token 估算（`tiktoken` + 启发式降级）**：精确预算上下文 Token，摆脱粗暴的 `max_count=40` 按条裁剪。
  - **轮次边界裁剪与 `sanitize()` 配对修复**：按 `USER` 边界逆序保留最近轮次，清除孤立 `tool` 或补全缺失结果，彻底杜绝 API 400 报错。
  - **原子落盘与路径穿越防护**：使用 `mkstemp + os.replace` 防止写一半崩溃毁文件，拦截 `../etc/passwd` 等非法 `session_id`。
- **改动文件**：`agent/llm/token_counter.py`、`agent/state.py`、`agent/memory/store.py`、`agent/memory/window.py`（待手敲）
- **验收命令与结果**：
- **掌握情况与踩坑记录**：

## 10.3 L2 异步滚动摘要
- **状态**：⬜ 待开始
- **预习知识点导览**（完成后补充实操细节与踩坑记录）：
  - **滑窗触发与 System Prompt 注入**：被窗口裁掉且尚未摘要的历史超过阈值时后台压缩成滚动摘要，保持长对话记忆连贯。
  - **乐观锁防并发覆盖（`created_at` + `summarized_upto`）**：防止旧快照回写时覆盖掉更新的摘要结果。
- **改动文件**：`agent/memory/summarizer.py`、`agent/memory/manager.py`（待手敲）
- **验收命令与结果**：
- **掌握情况与踩坑记录**：

## 10.4 L3 跨会话长期记忆（BM25）
- **状态**：⬜ 待开始
- **预习知识点导览**（完成后补充实操细节与踩坑记录）：
  - **多用户隔离事实库 + 中英文分词（单字/二元组）+ BM25 排序**：零外部向量库依赖实现高质量跨会话事实检索。
  - **工具层集成**：把 `remember_fact` / `recall_facts` 接入 `agent/tools/builtin.py` 并通过 `ToolContext.long_term` 注入。
- **改动文件**：`agent/memory/long_term.py`、`agent/tools/builtin.py`（待手敲）
- **验收命令与结果**：
- **掌握情况与踩坑记录**：
