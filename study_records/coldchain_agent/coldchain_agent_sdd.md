# 供应链冷链异常履约与协同 Agent（ColdChain-Agent）生产级系统设计文档（SDD）

> **来源说明**：本文档由归档 PDF 原件 [`./assets/coldchain_agent_sdd.pdf`](./assets/coldchain_agent_sdd.pdf) 完整转写整理（含原 PDF 中深色背景的架构图、5 张核心业务表 SQL DDL 与 `ColdChainState` 代码块还原），方便后续跨会话直接检索与编码对照。

这套「供应链冷链异常履约与协同 Agent」（以下简称 **ColdChain-Agent**）的核心定位，**不是一个陪聊的“智能客服”，而是一个嵌入在“门店报案 → 供应链中台 → 财务赔付/仓配补发”之间的自动化异常处置引擎**。

下面按照生产级系统设计文档（SDD）的标准，从业务痛点、整体架构、数据建模、核心状态机、工具与兜底机制、RAG 规则治理、全链路实战推演到评测落地，把这套系统彻底拆解清楚。你可以直接照着这份蓝图写代码，也可以把它当作面试时的架构底稿。

---

## 一、业务全景：它到底解决什么问题？边界在哪里？

在连锁茶饮与餐饮供应链中（如蜜雪冰城、瑞幸、霸王茶姬等），一旦涉及**鲜奶、鲜果、冷冻果浆、短保小料**等冷链物料，每天都会在全国数万家门店和数十个冷链仓之间爆发海量异常工单。

### 1. 传统人工处置的 4 大死穴
- **多方扯皮、定责极慢**：门店说“奶送来酸了”，但真相可能是仓库出库拿了临期品、可能是第三方冷链车半路关了制冷省油、也可能是门店签收后在常温下放了 4 小时自己捂坏的。客服专员得同时打开 **OMS（订单）**、**WMS（仓储）**、**TMS（物流温控）** 三个系统肉眼对账，一单耗时 20～40 分钟。
- **非标证据难以自动化**：门店发来的往往是口语化抱怨（“今天早上的奶全废了，赶紧赔钱！”）加上几张拍得歪歪扭扭的纸箱破损图、温度计照片、生产批号特写，传统固定表单和规则代码完全处理不了。
- **恶意套利与“人情单”漏洞**：部分加盟商可能拿上个月过期的旧货照片来冒充本次新货索赔，或者签收完好过了一天再报破损；人工在高并发工单下极易漏审，直接造成集团资损。
- **赔付/补发割裂**：定完责后，还得手动去提补发单、财务赔付单、承运商扣款单，极易漏提或重复建单。

### 2. ColdChain-Agent 的核心职责边界
- **输入**：门店通过飞书/工单端提交的非结构化异常描述 + 现场照片 + 订单号（或模糊提及“今天早上那车货”）。
- **处理**：自动提取非标证据 → 并发调取 OMS/WMS/TMS-IoT 客观事实 → 执行确定性交叉核验与金额计算 → 检索最新冷链赔付制度做软规则推理定责 → 按风险等级分流（🟢绿灯自动执行 / 🟡黄灯🔴红灯挂起人工审批）。
- **输出**：一份带完整证据链与制度引用的《定责分析报告》 + 自动触发下游动作（生成补发单 / 财务赔付单 / 承运商追责扣款单 / 驳回话术）。

---

## 二、整体技术架构：四层混合架构（确定性底座 + 概率性大脑）

这套系统最大的工程含金量，在于严格贯彻 **“Hybrid Control（混合控制）”** 原则：
- **大模型（LLM / VLM）只干三件事**：理解非标输入（看图/读口语）、结合模糊条款做定责归因、生成人话报告与沟通话术。
- **确定性代码（Python / SQL / 规则引擎）死守四条线**：所有时间差与金额计算、数据权限（RBAC）隔离、多源事实硬比对（批次号/超温时长）、写操作幂等与高危拦截。

```text
===============================================================================
                    [1. 交互与接入层 (Access Layer)]
  飞书机器人 / Web 门店报案端        运营审核后台 (SSE 实时流 + 人工审批卡片)
===================================│===========================================
                                   │ (REST / SSE 流式推送思考与工具轨迹)
                                   ▼
===============================================================================
               [2. Agent 编排与运行时层 (Workflow / LangGraph Runtime)]
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Stateful DAG / 有限状态机 (Checkpointer 持久化 & 断点续传)              │
  │                                                                         │
  │ [Node1 收单解析] -> [Node2 鉴权防重] -> [Node3 并发取证]                │
  │        -> [Node4 确定性交叉核验] -> [Node5 RAG 定责] -> [Node6 风险路由]│
  │                                            │                            │
  │                    ┌───────────────────────┴───────────┐                │
  │                    ▼ (绿灯: 低风险小额)                ▼ (黄/红灯)       │
  │       [Node7 动作执行器 + Saga 补偿]     [Interrupt 挂起: 人工协同审批] │
  └─────────────────────────────────────────────────────────────────────────┘
===================================│===========================================
                                   │ (MCP 协议 / 标准 Function Calling)
                                   ▼
===============================================================================
                    [3. 能力与工具层 (MCP Server + Engines)]
  ┌──────────────────────┬──────────────────────────┬───────────────────────┐
  │ 业务系统 MCP 工具     │ 确定性计算与规则层        │ 多模态 & 混合 RAG     │
  │ - OMS 订单查询        │ - 超温时长精准计算        │ - VLM 票据/批号识别   │
  │ - WMS 批次/称重       │ - 批次/效期硬校验         │ - BM25 + 向量混合检索 │
  │ - TMS IoT 温控日志    │ - 赔付金额公式引擎        │ - 元数据版本过滤+Rerank│
  │ - 补发/赔付写接口     │ - 幂等 Key & 红线阀       │ - 强引用溯源(Citation)│
  └──────────────────────┴──────────────────────────┴───────────────────────┘
===================================│===========================================
                                   ▼
===============================================================================
                  [4. 仿真业务底座 & 可观测层 (Digital Twin & Ops)]
       PostgreSQL / SQLite (5 张仿真业务表) │ Redis (幂等锁/缓存) │ 全链路 Trace
===============================================================================
```

> **一鱼两吃的架构价值**：这套架构用 `Python + 状态机/LangGraph + FastAPI + MCP/ToolRegistry` 写出来，直接打中一线城市硬核 Agent 研发岗；如果去面要求用 HiAgent / Dify 的业务落地岗，架构逻辑完全不变——只是把第 2 层的状态图映射为 HiAgent Workflow，把第 3 层的工具映射为 HiAgent 的自定义 API 插件即可。

---

## 三、仿真业务数据建模：5 张核心表设计

没真实公司数据没关系，用 PostgreSQL / SQLite 搭出下面 5 张高度仿真的业务表，并把它们拆分成独立的工具/API 服务（模拟企业真实的多系统孤岛），真实感立刻拉满：

### 1. OMS 订单与签收表（`oms_orders`）
记录门店买了什么、多少钱、什么时候签收的。

```sql
CREATE TABLE oms_orders (
    order_id      VARCHAR(32) PRIMARY KEY,  -- 订单号，如 ORD20261120001
    store_id      VARCHAR(32) NOT NULL,     -- 门店编号（RBAC 权限核心字段）
    brand_code    VARCHAR(16) NOT NULL,     -- 品牌隔离：MIXUE / LUCKY_COFFEE
    sku_code      VARCHAR(32) NOT NULL,     -- 物料编码，如 SKU_MILK_01
    sku_name      VARCHAR(64) NOT NULL,     -- 物料名称，如 巴氏杀菌鲜奶(1L*12/箱)
    temp_zone     VARCHAR(16) NOT NULL,     -- 温区要求：CHILLED(2~6℃) / FROZEN(-18℃) / AMBIENT
    ordered_qty   INT NOT NULL,             -- 下单箱数
    unit_price    DECIMAL(10, 2) NOT NULL,  -- 单箱供货价（赔付计算唯一基准）
    delivered_at  TIMESTAMP,                -- 物流送达时间
    signed_at     TIMESTAMP,                -- 门店签收时间
    sign_status   VARCHAR(16),              -- NORMAL(完好签收) / EXCEPTION(异常签收)
    sign_remark   TEXT                      -- 签收备注
);
```

### 2. WMS 仓储出库与批次表（`wms_shipments`）
记录仓库实际发了多少、发的是哪一批货、保质期到哪天、出库复核重量是多少（防“少发/发临期品”扯皮）。

```sql
CREATE TABLE wms_shipments (
    shipment_id      VARCHAR(32) PRIMARY KEY,
    order_id         VARCHAR(32) NOT NULL,
    warehouse_id     VARCHAR(32) NOT NULL,    -- 发货仓，如 WH_ZHENGZHOU_01
    batch_no         VARCHAR(32) NOT NULL,    -- 生产批次号（核验门店照片防造假核心！）
    prod_date        DATE NOT NULL,           -- 生产日期
    expiry_date      DATE NOT NULL,           -- 保质期截止日
    shipped_qty      INT NOT NULL,            -- 实际拣货出库数量
    expected_weight  DECIMAL(10, 2),          -- 理论整单重量(kg)
    actual_weight    DECIMAL(10, 2),          -- 出库复核称重(kg)（抓仓库漏发铁证）
    shipped_at       TIMESTAMP NOT NULL       -- 装车出库时间
);
```

### 3. TMS 物流与 IoT 温控时序表（`tms_iot_logs`）
模拟冷链车厢传感器每 15 分钟上报一次的真实温度轨迹（抓承运商断链铁证）。

```sql
CREATE TABLE tms_iot_logs (
    log_id         BIGSERIAL PRIMARY KEY,
    shipment_id    VARCHAR(32) NOT NULL,
    carrier_id     VARCHAR(32) NOT NULL,                 -- 第三方承运商 ID
    vehicle_plate  VARCHAR(16) NOT NULL,                 -- 车牌号
    recorded_at    TIMESTAMP NOT NULL,                   -- 采集时间戳
    temp_celsius   DECIMAL(5, 2) NOT NULL,               -- 车厢实测温度(℃)
    door_status    VARCHAR(8) DEFAULT 'CLOSED'           -- 车门开关状态（排查频繁开门导致升温）
);
```

### 4. 异常索赔工单表（`claim_tickets`）
记录全流程状态流转与幂等控制。

```sql
CREATE TABLE claim_tickets (
    ticket_id        VARCHAR(32) PRIMARY KEY,
    idempotency_key  VARCHAR(64) UNIQUE NOT NULL,        -- 幂等键：md5(order_id + sku_code + issue_type)
    order_id         VARCHAR(32) NOT NULL,
    store_id         VARCHAR(32) NOT NULL,
    issue_type       VARCHAR(32),                        -- SPOILAGE(变质) / SHORTAGE(少货) / DAMAGE(破损) / EXPIRED(临期)
    claimed_qty      INT,                                -- 门店声称受损箱数
    claimed_amount   DECIMAL(10, 2),                     -- 门店索赔金额
    calc_amount      DECIMAL(10, 2),                     -- 系统精准核算赔付额
    liability_party  VARCHAR(32),                        -- CARRIER(承运商) / WAREHOUSE(仓库) / STORE(门店自担) / FRAUD_SUSPECT(疑似欺诈)
    status           VARCHAR(32) NOT NULL,               -- INIT / NEED_INFO / PENDING_APPROVAL / APPROVED / REJECTED / EXECUTED
    evidence_urls    JSONB,                              -- 门店上传的图片 URL 列表
    verdict_report   JSONB,                              -- Agent 生成的结构化定责报告
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5. 审计与审批留痕表（`audit_trails`）
满足企业内控与可回溯要求，记录每一次 Agent 决策轨迹、人工干预动作与下游单据回执。

```sql
CREATE TABLE audit_trails (
    audit_id    BIGSERIAL PRIMARY KEY,
    ticket_id   VARCHAR(32) NOT NULL,
    actor_type  VARCHAR(16) NOT NULL,                    -- AGENT / HUMAN_OPERATOR
    action      VARCHAR(64) NOT NULL,                    -- VERDICT_GENERATED / HUMAN_APPROVED / REPLENISH_CREATED / COMPENSATED
    payload     JSONB NOT NULL,                          -- 快照：包含引用的制度条款、工具入参出参、人工修改原因
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 四、Agent 核心状态机拆解（7 个节点全流程）

**核心设计原则**：绝对不要用一个死循环的通用 ReAct Agent 去干这件事，那样不可控且极容易漏步。必须采用**显式状态图（FSM + DAG）**，把主干流程钉死，只在需要智能的地方挂载模型。

### 1. 全局状态定义（`ColdChainState`）

```python
from typing import Optional, TypedDict

class ColdChainState(TypedDict):
    # 1. 上下文与身份（系统硬注入，LLM 不可改）
    session_store_id: str          # 当前登录门店 ID（RBAC 强校验）
    ticket_id: str
    raw_message: str               # 门店口语报案文本
    image_urls: list[str]          # 现场照片

    # 2. 解析提取结果
    order_id: Optional[str]
    issue_type: Optional[str]      # SPOILAGE / SHORTAGE / DAMAGE / EXPIRED
    claimed_qty: Optional[int]
    vlm_findings: dict             # 视觉解析：{batch_no, expiry_visible, damage_level, is_clear}
    missing_fields: list[str]      # 缺失必要信息（用于触发多轮追问）

    # 3. 客观取证数据（来自 3 个独立业务系统）
    oms_data: dict
    wms_data: dict
    tms_iot_summary: dict          # 经确定性脚本统计后的温控摘要，绝不把几百行原始温度塞进 Prompt！

    # 4. 确定性交叉核验与核算结果
    cross_check_flags: list[str]   # 如 ["BATCH_MISMATCH", "TEMP_EXCURSION_CONFIRMED", "LATE_REPORT"]
    deterministic_calc: dict       # {hours_since_sign, max_excursion_mins, approved_amount}

    # 5. RAG 检索与最终定责
    retrieved_policies: list[dict] # 带条款 ID 和生效日期的制度原文
    verdict: dict                  # 强 Schema 定责结论：{party, risk_level, reasoning, citations, suggested_actions}

    # 6. 审批与执行状态
    human_decision: Optional[dict] # 人工审批回传：{approved: bool, adjusted_amount: float, comment: str}
    execution_results: list[dict]  # 下游接口执行回执
```

### 2. 七大核心节点与条件路由详解

#### Node 1: `intake_and_vlm_parser`（多模态收单与信息完整性校验）
- **干什么**：用 LLM 解析门店口语报案（提取订单号、异常类型、受损数量）；同时调用 VLM（或结构化特征提取）解析门店照片——重点抽取包装上的**生产批号、保质期、破损程度、图片是否模糊/翻拍**。
- **条件分支（反问追问机制）**：如果缺少关键信息（如没传订单号且按门店查不到今日唯一订单、或申报变质却没传带批号的照片），状态机直接走到 `ask_for_more_info` 节点中断挂起，回复门店：*“请补充清晰的外箱生产批号照片，以便系统核验批次”*，等用户补图后从 Checkpoint 续跑。

#### Node 2: `rbac_and_idempotency_guard`（纯确定性代码节点：权限与防重）
- **干什么（零 LLM 参与）**：
  1. **RBAC 校验**：查 `oms_orders` 确认该 `order_id` 的归属 `store_id` 是否严格等于当前登录态 `session_store_id`。如果不一致（防止门店乱填别人单号或 Prompt 注入越权查单），直接拦截终止。
  2. **幂等防重**：计算 `idempotency_key = md5(order_id + sku_code + issue_type)`，查 `claim_tickets`。如果该订单已理赔或正在审批中，直接返回现有工单进度，绝不重复建单。

#### Node 3: `parallel_evidence_gatherer`（并发多源取证）
- **干什么**：利用 Python `asyncio.gather`（或并行分支 Fan-out）同时调用 3 个独立子系统工具：
  - 调 OMS 取订单单价、温区要求、签收状态与签收时间；
  - 调 WMS 取发货数量、实际复核重量、发货批次号与保质期；
  - 调 TMS-IoT 取该运单全程温控时序日志，**并在工具内部直接完成聚合压缩**（只返回最高温、最低温、超温起止时间段、累计超温分钟数、开门异常次数），避免把 200 条原始 JSON 日志塞爆大模型上下文窗口。

#### Node 4: `deterministic_cross_validator`（核心灵魂：确定性交叉核验与算账引擎）
- **干什么**：纯 Python 规则引擎执行，**绝不让 LLM 心算**。对多源数据进行 5 维度硬碰撞，输出结构化异常标签（`cross_check_flags`）：
  1. **批次防伪比对**：`vlm_findings.batch_no` vs `wms_data.batch_no`。若两者均清晰提取却不一致 → 打标 `BATCH_MISMATCH_FRAUD_RISK`（疑似拿旧货/别家货顶包！）。
  2. **时效窗口精确计算**：`report_time - oms_data.signed_at`。例如破损类索赔超过签收 2 小时、或签收单勾选了“完好无损” → 打标 `LATE_REPORT` / `SIGNED_AS_NORMAL`。
  3. **温控达标硬判定**：结合 `oms_data.temp_zone`（如冷藏 2~6℃），调用确定性算法检查连续超温是否超过阈值（如 >8℃ 持续 ≥30 分钟）→ 打标 `CARRIER_TEMP_EXCURSION`。
  4. **少货重量交叉核验**：`wms_data.shipped_qty < oms_data.ordered_qty` 或 `(expected_weight - actual_weight)` 刚好约等于 `claimed_qty * 单箱毛重` → 打标 `WAREHOUSE_SHORTAGE_CONFIRMED`。
  5. **临期出库核验**：计算发货日距离 `expiry_date` 剩余保质期比例是否低于公司标准（如小于 1/3 效期）→ 打标 `WAREHOUSE_NEAR_EXPIRY`。
  6. **金额精准核算**：按公式 `approved_amount = min(claimed_qty, ordered_qty) * unit_price * 对应赔付比例` 精确算出金额（保留两位小数），写入 `deterministic_calc`。

#### Node 5: `policy_rag_and_liability_judge`（动态制度检索 + 软规则推理定责）
- **为什么还需要 LLM？** 因为真实业务里经常出现**多因并发或例外条款**——比如“车厢确实超温了 25 分钟（未达 30 分钟硬线），但当时是 40℃ 极端高温且门店反映奶已结块，同时配送延迟了 3 小时”，或者需要结合具体品牌/大区的特殊免责政策做综合权衡。
- **干什么**：
  1. 根据 `brand_code`、`temp_zone`、`issue_type` 和当前生效日期作为 **Metadata Filter**，从混合检索引擎（BM25 + 向量 + Rerank）精准召回 3～5 条最相关的《冷链赔付规范》原文。
  2. 将“客观证据 + 确定性核验标签 + 精准算出的金额 + 制度原文”喂给大模型，强制要求按 Pydantic JSON Schema 输出最终定责对象：包含责任方、风险等级（`GREEN` / `YELLOW` / `RED`）、逐条证据推理链、引用的具体条款编号及建议执行动作。

#### Node 6: `risk_router_and_hitl`（风险路由与人机协同挂起）
通过条件路由硬性分流，**不管 LLM 怎么判，红线由代码强控**：
- 🟢 **绿灯（自动闭环）**：同时满足 `风险等级 == GREEN` 且 `无欺诈/超时矛盾标签` 且 `赔付金额 <= 500 元` → 直接进入 Node 7 自动执行。
- 🟡 **黄灯（超额或边缘争议）**：证据链完整但 `赔付金额 > 500 元`，或存在多方混合责任（如仓内临期 + 运输轻度超温）→ 触发 **Checkpoint 挂起（Interrupt）**，向审核后台推送《AI 初审卡片》，等待人类运营点击【同意 / 调整金额 / 驳回】后唤醒恢复。
- 🔴 **红灯（高危拦截）**：命中 `BATCH_MISMATCH_FRAUD_RISK`（批次造假嫌疑）或 `LATE_REPORT` 且门店情绪激烈 → 严禁自动赔付，直接挂起流转至高级风控/人工客服介入。

#### Node 7: `action_executor_with_saga`（动作执行与 Saga 补偿机制）
- **干什么**：确认通过后，按定责结果调用下游写接口（例如：承运商责任 → 既要给门店建补发单/余额赔付单，又要给承运商建结算扣款单）。
- **后端硬核亮点（Saga 补偿）**：这是典型的跨系统分布式写操作。如果第 1 步“给门店建补发单”成功了，但第 2 步“给承运商建扣款单”因网络超时失败，执行器会先做指数退避重试；若依然失败，不会让数据停在半吊子状态，而是触发逆向补偿（`rollback_action`）或写入异常补偿队列并通知人工兜底，全过程写入 `audit_trails` 留痕。

---

## 五、标准化工具层设计（MCP Server / ToolRegistry 接口清单）

| 工具名称 (Tool Name) | 性质 | 核心入参 | 核心出参 / 防呆设计 |
| :--- | :--- | :--- | :--- |
| `get_order_and_sign_info` | 只读 (`READ_ONLY`) | `order_id`（`store_id` 由 `ToolContext` 上下文隐式注入） | 订单明细、单价、温区、签收时间与状态；**拒绝跨门店查询** |
| `get_wms_shipment_detail` | 只读 (`READ_ONLY`) | `order_id` | 批次号、生产/到期日、实发数、理论重 vs 复核实重 |
| `analyze_tms_temp_excursion` | 只读+计算 (`READ_ONLY`) | `shipment_id`, `min_temp`, `max_temp` | **工具内完成聚合计算**：返回超温总分钟数、最长连续超温段、峰值温度、开门次数 |
| `search_coldchain_policy` | RAG 检索 (`READ_ONLY`) | `query`, `brand_code`, `issue_type`, `temp_zone` | 带 `doc_id`、`clause_no`、`effective_date` 的精准制度片段 |
| `create_replenishment_order` | 写入/幂等 (`HIGH_RISK`) | `ticket_id`, `order_id`, `sku_code`, `qty`, `idempotency_key` | 补发单号；底层带幂等表校验 |
| `create_financial_claim` | 写入/幂等 (`HIGH_RISK`) | `ticket_id`, `amount`, `liability_party`, `idempotency_key` | 财务赔付/承运商扣款单号；**强制校验金额 ≤ 订单总额** |
| `rollback_action` | 补偿 (`WRITE`) | `action_type`, `external_doc_id`, `reason` | 取消已创建的下游单据（用于 Saga 事务回滚） |

---

## 六、RAG 知识库设计：彻底告别“玩具级切片”

把 RAG 做成“高精度规则引擎的左膀右臂”，重点体现三个生产级细节：
1. **文档内容结构化建模**：编写贴近真实连锁餐饮标准的 Markdown 文档《连锁餐饮冷链履约异常定责与赔付管理规范（2026版）》，拆分为 5 大章：
   - 第 1 章：各温区物料标准阈值（如鲜奶冷藏 2~6℃，连续超 8℃ 达 30 分钟判定失温；冷冻果浆 -18℃ 以下，高于 -12℃ 达 45 分钟判定解冻风险）。
   - 第 2 章：报案时效与证据要求（破损/少货需签收 2 小时内提报；变质/临期需 24 小时内提报并附带清晰生产批号照片）。
   - 第 3 章：三方定责矩阵（仓库责任 / 承运商责任 / 门店自担 / 极端天气不可抗力分摊比例）。
   - 第 4 章：不同品牌与大区差异化条款（如 `MIXUE` 与 `LUCKY_COFFEE` 的保质期红线差异）。
   - 第 5 章：自动审批与风控红线（500 元以内绿灯自动批；500~2000 元区域运营批；2000 元以上或涉欺诈嫌疑升级风控）。
2. **元数据强过滤（Metadata Filtering）**：切片时按**条款级（Clause-level）**切分，绝不按固定字数硬切导致“条件和结论被切开”。每个 Chunk 挂载元数据：`{brand_code, temp_zone, issue_type, effective_from, is_active}`。查询时先按元数据硬过滤掉废止版本和其它品牌的条款，再做 BM25 + 向量检索。
3. **强制引用溯源（Grounded Citation）**：Prompt 约束大模型每下一句定责结论，必须标注 `[条款 3.2.1]`，后端代码校验该编号确实存在于本次检索结果中，杜绝模型凭空捏造条款。

---

## 七、全链路实战推演：两个经典冲突案例

### 案例 A：承运商断链实锤 + 超额触发人工审批（🟡 黄灯）
- **门店输入**：“订单 `ORD20261120008` 今天早上送来的 15 箱巴氏鲜奶全是温的，开了一箱已经发酸，申请全额赔付！” + 附上 2 张带清晰批号和测温枪（显示 13℃）的照片。
- **系统流转**：
  1. **Node 1**：提取 `order_id=ORD20261120008`, `issue_type=SPOILAGE`, `claimed_qty=15`, 照片批号 `B20261118`, 测温读数异常。
  2. **Node 2 (Guard)**：校验订单归属当前门店（通过），幂等检查未重复报案（通过）。
  3. **Node 3 (并发取证)**：
     - OMS：鲜奶 15 箱，单价 68 元/箱，温区 `CHILLED(2~6℃)`，11月20日 07:10 异常签收。
     - WMS：发货批号 `B20261118`，保质期至 11月27日（未临期）。
     - TMS-IoT 工具聚合：凌晨 04:15~05:30 车厢温度飙升至 11.8℃，**连续超温 75 分钟**，期间无开门记录（制冷机疑似故障/关闭）。
  4. **Node 4 (确定性交叉核验)**：
     - 批次比对：`B20261118 == B20261118`（真实性校验通过）；
     - 报案时效：距签收 0.8 小时（合规）；
     - 温控判定：75 分钟 > 30 分钟红线 → 打标 `CARRIER_TEMP_EXCURSION`；
     - 精确算账：`15 * 68.00 = 1020.00` 元。
  5. **Node 5 (RAG + 推理)**：召回 `[条款 1.1]` 与 `[条款 3.2]`，输出定责：**承运商全责**，建议全额赔付门店 1020 元并加急补发，同时向承运商扣款 1020 元。
  6. **Node 6 (风险路由)**：虽然证据链 100% 实锤，但 `1020.00 > 500.00`（触发金额红线）→ **强制挂起（Interrupt）**，前端弹出审核卡片。
  7. **Node 7 (人工放行后执行)**：运营核对无误点击【批准】，系统从 Checkpoint 恢复，幂等写入补发单 + 财务赔付单 + 承运商扣款单，全程留痕。

### 案例 B：拿旧货照片顶包套利（🔴 红灯秒拦截）
- **门店输入**：“`ORD20261120019` 这批冷冻柠檬汁刚送来就发胀变质了，赔 300 块！” + 上传 1 张外箱照片。
- **系统流转**：
  - 如果只看金额（`300 元 <= 500 元`），普通低代码机器人可能就傻傻自动赔了。
  - 但在 **Node 4** 中，从照片角落提取出的生产批号是 `B20260805`，而 WMS 记录本次发出的批次是 `B20261112`，且 TMS 温控全程稳定在 -19.2℃ 无任何波动。
  - 系统瞬间打出 `BATCH_MISMATCH_FRAUD_RISK` 与 `TEMP_NORMAL` 两个红标 → 强制路由至 **🔴红灯风控挂起**，向运营输出高亮预警：*“疑似旧货顶包：照片批次(B20260805)与本次出库批次(B20261112)不符，且全程冷链温控达标，已拦截自动赔付”*。

---

## 八、可观测性与自动化评测指标（40 条 Golden 测试集）

构造 40 条仿真用例：
- 正常承运商断链（10 条）
- 仓库漏发/临期（8 条）
- 门店超期/签收完好无理索赔（8 条）
- 批次造假/跨店越权攻击（6 条）
- 信息缺失需多轮追问（4 条）
- 多因复合边缘争议（4 条）

**输出 5 个可写进简历的硬指标**：
1. **定责准确率**（对比“纯 Prompt 基线” vs “混合架构版”，如 64% → 95%+）；
2. **高危欺诈/越权拦截率**（硬指标必须做到 100%）；
3. **金额计算零误差率**（纯代码计算保证 100%）；
4. **工具调用轨迹合规率（Trajectory Accuracy）**（是否按序查齐了必需系统、无多余死循环调用）；
5. **单工单平均耗时与 Token 成本**（全链路 Trace 统计每个节点的延迟与费用分布）。
