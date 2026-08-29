# PLAN — 商业建模工作台：可信计算 + 薄引擎架构改造

> 本计划基于 2026-07-09 的逐轮讨论共识整理。目标不是"把系统做更复杂"，而是让它**在稀疏输入下诚实、可信、不膨胀**，并为"LLM 给建议"留出干净的接口。

---

## 0. 背景与共识

### 0.1 问题根因（代码为证，`src/tools/workflow_engine.py`）
- `monthly_rent=8000` → `monthly_fixed_cost=20000`：人工 `2×6000=12000` 来自 FALLBACK 模板默认（`_resolve_industry("其他")` → FALLBACK_TEMPLATE，line 365-367 / 425 / 434），标签却只写 `[推算] 租金+人工`，掩盖"人工=虚构"。
- `available_cash=0.0`：`total_investment` 缺失被当 0，`available_cash = 0×(1-设备占比)` 算出 0，来源标 `[推算]` 而非 `[缺失]`（line 438-439）。
- 连锁误报：营收=0 → 利润=-20000；`available_cash=0` 传入 `pitfall_detector` 的 `runway=current_cash/net_burn` → runway=0 → 状态🔴危险 + 现金流告警。整套"危险"诊断建立在虚构前提上。

### 0.2 架构总纲（核心共识）
```
薄引擎(只算已知的)  →  ①②(标注 已知/猜的/缺的)  →  LLM(基于标注给建议)
```
- ①② 是桥梁：让薄引擎可信（不再假精确）+ 给 LLM 干净、有边界的输入（不飘）。
- 它**不增加膨胀**（体量 40–230 行），也**不滑向聊天噪音**（输出有结构、有边界）。

---

## 1. 分阶段实施

### Phase 0 — MVP 地基：置信层 + 门禁 + 默认策略（P0，先做）
**目标**：消灭误报 / 不让未知=0 / 不让 6000 静默算 / 缺失即停算。

| 编号 | 改动 | 位置 |
|------|------|------|
| P0-1 | 缺失传播：`total_investment` 缺失 → `available_cash` 标 `[缺失]` 而非 `[推算]` 算出 0 | `workflow_engine.py` `_fill_params` line 438-439 |
| P0-2 | 默认人力策略（决策 A，推荐①③组合）：未给行业且未给人力 → `employee_count/avg_salary` 默认 0、标 `[缺失]`，**不静默用 6000**；同时保留"模板假设"作为可见、可内联修改的选项 | `_fill_params` line 360-367 |
| P0-3 | 来源拆分：`monthly_fixed_cost` 的 `[推算] 租金+人工` 拆为 `租金[用户] + 人工[默认/缺失]` | `_fill_params` line 434-435 |
| P0-4 | 置信档位 `conf`：从现有 `src` 字符串派生 tier `{user/default/guess/missing}` 附到每个参数 | `_fill_params` |
| P0-5 | 门禁 `_check_sufficiency()`：核心字段（营收路径 / 总投资）缺失 → 返回"骨架"响应（收入/成本模型框图 + 缺口高亮 + 只算已知部分），**不输出仪表盘与危险判定** | `quick_scan` |
| P0-6 | `current_cash` 改 `is not None` 判定：缺失传 `None` → 跳过现金流/跑道判定，不触发 runway=0 误报 | `pitfall_detector.py` `_do_full_scan` ~line 441 |
| P0-7 | 渲染"可信度"列；`[缺失]` 行显示"未知/待填"（改造 line 67 的跳过逻辑） | `formatter.py` `_fmt_scan` |
| P0-8 | 测试用例 `{monthly_rent:8000}` 断言返回"参数不足"骨架 | `tests/` |

**代码量**：最小可用 ~40 行（P0-1 + 门禁跳过）；完整 ~230 行。

### Phase 1 — 灵活度层（P1）：③④⑤⑥
- **③ 区间/情景引擎**：输出范围而非单点；把 `sensitivity` 提为头条。
- **④ 共享校验态 `ProjectState`**：`quick_scan / trend_projection / compare_scenarios` 共用一次校验+标注，避免各自重算不一致。
- **⑤ 叙事 > 判决**：状态从 🔴危险 → "风险集中在 X 假设，你最该质疑 Y"。
- **⑥ 模板当分布**：12 模板点值 → 区间（如餐饮变动成本率 `0.40±0.08`），采样出弹性。

### Phase 2 — LLM 协作层（可选，架构落点）
- 把 ①② 产出的**置信对象**作为 LLM 输入，使建议基于标注、不飘。
- 是否启动取决于产品是否要"LLM 给建议"功能。

### Phase 3 — 跨轮对齐层（P3）：SessionState + 抽取修复 + LLM 接地【待实施，2026-07-09 诊断后新增】
> **背景**：Phase 0/1/2 全是 **single-shot**（一次输入→一次分析）。用户实测羊肉汤店对话暴露 3 个叠加 bug，根因是**系统有「规则引擎」和「LLM agent」两套互不共享状态的路径，无唯一真相源**（即用户说的"大模型跟项目分离"）。
> **结论（用户已认同）**：不靠"给 LLM 加智能体"（会放大幻觉），而是**优化运行逻辑**——让 SessionState 成为唯一真相源，LLM 降级为只读反射子组件。正确架构 = 编排者(结构化引擎+SessionState) + LLM(接地反射)，这本身就是"真·智能体"但自主权在引擎。

| 层 | 编号 | 改动 | 落点 & 代价 |
|----|------|------|-------------|
| **第0层 上下文累加** | P3-0 | 新增 `src/session_state.py`：以 `thread_id` 为键存 `{params, industry}`；每轮 `merged = merge(旧, 新)` 后再 `quick_scan`，并回写。把 `你再算一下/改成/加上/补充` 识别为**续算意图** → 强制走 merge，不重新抽取、不进 chitchat | web_server `/chat` 步骤2 改造；新文件 ~60–90 行 |
| **第1层 数据对齐(入)** | P3-1 | 修 `param_extractor.py`：① `_cn_to_num` 支持万/千量级（"一万二"→12000，而非只取"一"=1.0）；② `total_investment` 关键词补"投资"（现只认"总投资"）；③ 行业识别补"羊肉汤/汤店/面馆"等餐饮细分；④ 补"人工/员工"→employee_count/avg_salary 识别 | `param_extractor.py` ~30–50 行 |
| **第2层 数据对齐(出)** | P3-2 | **业务消息永不走自由 agent**（`agent.py`）；LLM 唯一出口是 `llm_advisor.advise`（只读 structured JSON）。即便真 chitchat，也把 SessionState 注入 system context，防止模型凭记忆编造（如"成都冒菜店/7.5万"幻觉） | `web_server.py` 路由约束 + `agent.py` system prompt ~20–40 行 |

**回归验收（用用户羊肉汤店对话）**：
- Turn1 `开羊肉汤店，投资20万，单价15，月营收2万，房租一万二` → 应抽成 `industry=餐饮, monthly_rent=12000, total_investment=200000, price=15, monthly_revenue=20000`（而非 rent=1.0 / investment 漏抓 / industry=None）。
- Turn2 `人工成本2人8000，固定成本2500，你再算一下` → 应**自动 merge** 出完整仪表盘（含人工8000+固定2500+租金12000），**不报"信息不全"**，不进入自由 agent 编造。
- 新增 `tests/test_phase3_session_alignment.py` 覆盖：跨轮 merge、中文数字解析、续算意图识别、业务消息不漏给 agent。

**代码量**：Phase 3 约 110–180 行（新文件 session_state + 抽取修复 + 路由约束），不引入新依赖。

---

### Phase 4 — 工作台一体化（引擎补全 + 路由收口 + 抽取器防误抓）【计划，待实施】
> **背景（用户 12 轮羊肉汤店对话实测，2026-07-09 晚）**：Phase 0–3 只解决了「跨轮遗忘 / 抽取脏入 / 幻觉」。但对话进一步暴露更深层问题——**引擎作为唯一真相源，成本模型是残缺的；同时「结构化引擎」与「自由 LLM agent」仍是两套互不联通的脑子**。具体症状（代码为证）：
> - 固定成本只算 `租金+人工`（`workflow_engine.py` line 449），水电/包装/提成无字段接 → "太离谱"/21,000 半截模型。
> - 无单位变动成本字段，变动成本率只吃行业默认 40% → "可变成本是我猜的"。
> - 营收被早期显式值钉死（line 428-435）→ "40×15×30=1.8万但分析给2万"。
> - 问句（"减租好还是提价好"）漏进自由 agent 自算 → "给了又问/两套数字"。
> - 抽取器在问句里误抓（"我把月固定成本每一项都给你了"→ monthly_fixed_cost=1.0）。
> - 跑道亏损时兜底"无限"（line 899/912）→ 假象。
>
> **北极星（用户已认同）**：**引擎 = 工作台（确定性真相源），LLM = 内置引擎管理者（Engine Steward）**。不是重写引擎，而是「补全引擎 + 把 LLM 收编进引擎」。LLM 不再只是「被动翻译仪表盘」，而是工作台的**管理者**——对引擎保持「只读数据 + 运维权限」的纪律（可读取状态/结果、调度计算、调设置、提议代码修复），对用户做对账/诊断/编排、输出冷静接地的解读；但**绝不修改引擎数据、绝不自由计算**（C3）。此法把「数据权限」与「工具权限」彻底切开，从根上消除「两套数字」。

**模块边界与协作契约**（见对话内模块图）：

| 契约 | 规则（已锁定） |
|------|----------------|
| **C1 成本聚合** | 组件（租金/人工/水电/包装/提成/其他）给齐 → 引擎**自动求和**；仅当用户显式给总数但组件不全时，以显式总数为兜底。用户不必手算。 |
| **C2 营收派生** | `monthly_revenue` 以「最近一次用户显式给出的」为准；仅缺失时用 `日客流×客单价×(30或growth)` 派生，显式值不被覆盖。 |
| **C3 LLM 护栏** | worker 是「引擎管理者」而非「自由计算器」：对引擎**只读数据**（读取操作状态/操作结果，绝不修改参数 / SessionState / 计算结果），可运维（调度引擎计算、调设置、提议代码修复）；**任何面向用户的数字必来自引擎结构化输出**。数据只来自用户原始输入(经抽取器)或引擎确定性推导(C1/C2)，LLM 永不直接写数据（红线）。 |

| 编号 | 改动 | 落点 & 代价 |
|------|------|-------------|
| P4-0 | **固定成本组件化**：新增 `utilities(水电)/packaging(包装)/commission(提成)/other_fixed(其他固定)` 字段；引擎 `monthly_fixed_cost = rent + labor + utilities + packaging + commission + other_fixed`（逐项标 `[用户]`），仅组件不全且用户给显式总数时兜底 | `workflow_engine.py` `_fill_params` ~40–60 行 |
| P4-1 | **单位变动成本**：新增 `unit_variable_cost`；给"每份成本12元" → 与 `price_per_unit` 推 `variable_cost_ratio = unit_var/price`（标 `[推导]`）；否则沿用显式 ratio 或行业默认（标 `[默认]`） | `workflow_engine.py` ~20–30 行 |
| P4-2 | **营收派生修正**：`monthly_revenue` 取最近一次显式值；缺失才派生；显式不被覆盖（修"2万被钉死"） | `workflow_engine.py` + `session_state` 优先级 ~20 行 |
| P4-3 | **路由收口(B)**：所有业务轮（含 what-if/对比/保本问句）统一进引擎；问句类意图用引擎 `compare_scenarios`/`breakeven` 出数；`get_agent()` 自由算彻底移除，LLM 仅 `llm_advisor.advise` 只读 | `web_server.py` + `intent.py` ~30 行 |
| P4-4 | **抽取器防误抓(C)**：`monthly_expense/固定成本` 等关键词要求「概念+数字+单位」才抽；问句/修辞语境抑制取值，避免从"月固定成本"误捞"一"→1.0 | `param_extractor.py` ~30 行 |
| P4-5 | **跑道修正**：亏损且 `available_cash` 有值 → 有限跑道（现金/月净烧）；仅现金缺失时标 `[缺失]`，不兜底"无限" | `workflow_engine.py`/`financial_calculator` ~10–20 行 |
| P4-6 | **回归测试** `test_phase4_workbench.py`：用用户 12 轮对话固化 oracle。关键断言：固定成本=12000+8000+800+260+1000=22060；"每份12+客单价15"→变动率80%；显式营收2万优先于派生；无行业默认工资误算；亏损+现金8万→跑道≈10月 | `tests/` ~12–15 用例 |
| P4-7 | **LLM 角色升级：引擎管理者（Engine Steward）** | 将 LLM 从「被动翻译器」升级为「引擎管理者」——对用户是协作者、对引擎保持「只读数据 + 运维权限」的纪律（严守 C3）。权限矩阵：① **可读**引擎操作状态(报错/延迟/一致性)与操作结果(scan/仪表盘/假设清单含 conf 来源)；② **可调度**引擎计算(compute/compare/breakeven)，纯读/算不改数据；③ **提议**改引擎设置/配置(有界，且绝不含用户财务数值)与**提议代码修复**(结构化 AnomalyReport，经测试门禁，绝不运行时 exec/eval/写文件)；④ **绝不可改引擎数据**(参数/SessionState/计算结果)——数据只来自用户原始输入(经抽取器)或引擎确定性推导(C1/C2)；⑤ **运维闭环**：监控引擎输出→检测异常(如 fixed_cost=1.0 抽取 bug、22060 半截模型)→提代码修复→测试门禁→引擎更健康。对话侧职责(对用户)：对账(发现矛盾+**提问**而非默默采纳)、诊断(单一最高杠杆)、编排(模糊目标→引擎操作)、冷静默认话术 | `llm_advisor.py` + `web_server.py` 调用处 ~60–90 行 |

**代码量**：Phase 4 约 210–320 行（纯增量，不引入新依赖）。

### Phase 5 — 对比 / what-if 工作台（compare 做厚）【计划，待确认】
> 承接决策：A+B+C 底座先做扎实，compare/what-if 作为下一阶段增强（用户已认同此分层）。
- **P5-0** 把「减租好 vs 提价好」「调到多少能保本」做成引擎内 `compare_scenarios`：输入当前 SessionState + 用户提案，输出多方案并排利润/保本点；LLM 只解读。
- **P5-1** `breakeven` 工具：给定固定成本+变动率，反推所需客流/客单价。
- **P5-2** 测试 `test_phase5_whatif.py`。

---

### Phase 4 可执行性细则（落地前必读）

> 本小节把上面的契约与子项变成「可照着写、写完能验」的规格。实施时严格按此处判定逻辑写代码，不另立规则。

#### (a) 单轮执行时序（模块边界 = 谁碰数据）

```
用户消息 text
  │
  ├─[1] extract_params(text)                # 抽结构化参数（P4-4 防误抓生效点）
  ▼
  ├─[2] SessionState.apply_turn(tid, params, text)   # 跨轮 merge（P3 已落地）
  │       返回 merged（含 C2：显式营收优先、不被派生覆盖）
  ▼
  ├─[3] workflow_engine.quick_scan(merged)   # 引擎唯一计算点（P4-0/1/2/5 生效）
  │       返回 scan：核心指标 + 参数(含 conf/来源) + 假设清单 + 情景 + 风险
  ▼
  ├─[4] formatter.format_response(scan)      # 仪表盘文本
  ▼
  └─[5] llm_advisor.advise(scan, session_snapshot, text)  # 引擎管理者（P4-7，只读）
          读 scan+状态 → 对账/诊断/编排 → 输出解读；绝不写 merged/状态/scan
  ▼
返回 {content: 仪表盘+💡解读, params: merged}
```
**红线**：步骤 [3] 之外不存在任何计算；`get_agent()` 在业务路径中被删除（P4-3）。LLM 要任何数字只能走 [3] 或 `compare_scenarios`/`_calc_breakeven`（同在引擎内，仍是引擎算）。

#### (b) 契约判定逻辑（实施伪代码）

**C1 成本聚合**
```
组件 = {rent, labor, utilities, packaging, commission, other_fixed}
labor = 显式labor_total 或 employee_count×avg_salary   # avg_salary 优先取用户给的
present = {k:v for k,v in 组件 if v is not None}
if present:
    sum_ = Σ present.values()
    if 显式 total_fixed_cost 给定:
        if |sum_ - total_fixed_cost| ≤ 1:  fixed = sum_          # 标[用户]
        else:  标记矛盾 → steward 提问"组件和=sum_，你给的总数=total，以哪个为准？"（不静默选）
    else:     fixed = sum_                                     # 标[用户]，自动求和
else:  # 组件全缺
    fixed = 显式 total_fixed_cost（兜底，标[用户]） 或 [缺失]    # 绝不猜 0 / 绝不猜"租金+人工"
```
关键：组件给齐 → **永远自动求和，绝不向用户要总数**（消除 T14 怒点）。

**C2 营收派生**
```
explicit_rev = SessionState 中「最近一次用户显式月营收」的值
if explicit_rev is not None:
    revenue = explicit_rev                                    # 标[用户]，显式优先
elif price_per_unit and daily_traffic:
    g = growth_rate if growth_rate 是用户给的 else 0
    revenue = price × traffic × 30 × (1+g)                    # 标[推导]
else:
    revenue = [缺失]
# 仅给 price×traffic 而未说"月营收" → 不覆盖已有 explicit_rev（修 2万被钉死）
```

**C3 LLM 护栏（执行机制，非口号）**
```
- advise(scan, session_snapshot, user_text) 的三个入参都是不可变快照（dict copy），
  函数体内不持有 SessionState/params 的任何写引用。
- 所有数字来自 scan（引擎算的）；advise 体内不得出现任何新的算术表达式。
- 需要 what-if 数时，advise 只能调用引擎工具 compare_scenarios / _calc_breakeven
  （同进程、仍是引擎算），把结果回填解读。
- 「修改代码/设置」仅以结构化 AnomalyReport（异常描述 + 建议补丁 + 应覆盖的测试）
  输出给开发者/日志；绝不运行时 exec/eval/写文件。代码改动由人 review 后落地，
  且必须通过 tests/run_all.py 全绿门禁。
```

#### (c) P4 每步验收断言

| 子项 | 完成后必须满足（断言） |
|------|------------------------|
| P4-0 | 给定 rent=12000,labor=8000,util=800,pack=260,comm=1000 → `monthly_fixed_cost == 22060` 且来源全 `[用户]`；组件不全且无总数时标 `[缺失]` 而非 0 |
| P4-1 | 给定 unit_variable_cost=12, price=15 → `variable_cost_ratio == 0.80`（标`[推导]`）；显式 ratio 优先于推导 |
| P4-2 | SessionState 含显式 revenue=20000；即便后续给 price=15×traffic=40（派生 18000），`revenue` 仍为 20000 |
| P4-3 | `web_server.py` 业务路径无 `get_agent()` 调用；what-if 问句路由到 `compare_scenarios`/`breakeven` 并经引擎出数 |
| P4-4 | `extract_params("你的意思是不是我把月固定成本每一项都给你了…")` 不产出 `monthly_fixed_cost`（或值≠1.0）；问句/修辞语境抑制取值 |
| P4-5 | profit=-8000 且 cash=80000 → `runway ≈ 10`（有限）；仅 cash 缺失时标 `[缺失]` |
| P4-6 | `test_phase4_workbench.py` ≥12 用例全过，含下方 12 轮 oracle |
| P4-7 | advise 入参为只读快照；对「减租好还是提价好」调用 `compare_scenarios` 出数；输出含对账/单一杠杆/最多一个下一步；不写任何数据 |

#### (d) 12 轮对话回归 oracle（验证"协作良好"的硬标准）

以用户贴出的羊肉汤店真实对话为集成测试输入，逐轮断言**修复后**应有的正确行为：

| 轮 | 输入（摘） | 修复后断言 |
|----|-----------|-----------|
| T1+T2 | 羊肉汤店/投资20万/客单价15/员工2人共8000 + 月营收20000 | 抽 industry=餐饮、labor=8000（非默认7000）、revenue=20000[用户]；租金未给→fixed 含 `[缺失]`，**不索要总数** |
| T3 | 月租金8000元，怎么收支平衡 | fixed=租金8000+人工8000=16000[用户]（自动求和）；steward 调 breakeven 给保本流量≈59/天；**不追问总数** |
| T4 | 租金+人工20000,客单价15,每天流量40 | 组件和=16000 与显式"20000"矛盾 → steward **提问澄清**，不静默取 20000；revenue 仍 20000（C2） |
| T5 | 租金12000,人工两人各4000,其他1000 | avg_salary=4000[用户]（修 7000 误算）；rent=12000 覆盖；other_fixed=1000 |
| T9 | 每份成本12元,水电800,包装260,提成1000 | **fixed=12000+8000+800+260+1000=22060[用户]**（C1 核心断言）；unit_var=12+price15→ratio=0.80[推导] |
| T10 | 月租减半到6000好，还是客单价提到20好 | steward 调 `compare_scenarios`（rent→6000 vs price→20）并排利润；无自由心算 |
| T11 | 变动成本率75%,客单价15,日均40,月租12000 | ratio=0.75[用户]（显式优先于推导）；fixed=22060 保留 |
| T12 | 月租改6000,需卖多少流量保本 | breakeven 用 fixed=14000(6000+8000)、ratio=0.75、price=15 出流量；数来自引擎 |
| T14 | "我把月固定成本每一项都给你了，还得给总数？" | extractor **不抓** monthly_fixed_cost=1.0；回应"已自动加总，无需你算" |
| 全程 | — | revenue 恒为 20000[用户]（跨轮不丢）；avg_salary 恒 4000[用户]；跑道有限非"无限" |

> 注：`compare_scenarios(base_json, alt_json)` 与 `_calc_breakeven(fixed, price, unit_var)` 在当前 `workflow_engine.py` / `financial_calculator.py` **已存在**，P5 是「做厚 + 接线」而非从零造。跑道"无限"的根因在 `financial_calculator._calc_runway`：`net_burn≤0` 才返回无限；亏损且有现金时 net_burn>0，P4-5 须确保此时传对 `monthly_burn_rate` 与 `current_cash`，得出有限跑道。

#### (e) 定义完成（Definition of Done）与回滚

- **Phase 4 DoD**：`tests/run_all.py` 全绿（原 26 + 新增 ≥12）；手动重放上述 12 轮，每轮 fixed/revenue/avg_salary/runway 与 oracle 一致；`grep -n "get_agent" web_server.py` 业务路径无命中。
- **回滚策略**：每个 P4 子项是独立函数 + 独立测试，互不影响；某步退化时前序已验证步骤不动。Steward 的代码建议**永不自动落地**（人审 + 测试门禁），故不存在"LLM 改崩引擎"的风险。
- **诚实边界**：C3 中"LLM 修改代码/设置"= **提议权**，非**执行权**；运行时可调的"设置"仅限解读风格/优先级展示，绝不含用户财务数值。

#### (f) Phase 4 逐步施工清单（Step-by-Step，照此顺序施工，每步独立可验）

> 本清单把 P4-0~P4-7 拆成**原子步骤**（S4-x.y），每步含：改哪个文件:函数 → 具体动作 → 自测命令 → 完成判定。严格「一步一测」，前一步 run_all 全绿才进下一步。

**施工前校正（与真实代码对齐，2026-07-10 核对）**：
- 抽取器真实路径为 `src/router/param_extractor.py`（非 `src/tools/`）。
- 固定成本聚合真实落点：`workflow_engine.py` `_fill_params` **line 437-454**（当前 `else` 分支只算 `rent+monthly_labor`）；营收派生 **line 428-435**；可用现金 **line 456-462**。
- 变动成本率逻辑在 `_fill_params` **line 343-357**（当前无 `unit_variable_cost` 字段）。
- `llm_advisor.advise` 当前签名是 `advise(scan, user_text="")`，P4-7 需扩为 `advise(scan, session_snapshot, user_text="")`。
- 跑道"无限"在 `financial_calculator.py` **两处**：`_calc_runway`(line 122-126) 与 `calculate_runway`(line 403-435)，P4-5 两处都要改；引擎侧入口是 `workflow_engine._safe_runway`(647)/`_runway_numeric`(715)。

**基线与自测命令**（每步复用）：
```
# 基线（改前必跑，须 26 绿）
.venv/bin/python3 tests/run_all.py
# 单文件快跑（示例）
.venv/bin/python3 tests/test_phase4_workbench.py
# 路由收口验证
grep -n "get_agent" web_server.py src/router/*.py
```

**S4-0 准备**：新建 `tests/test_phase4_workbench.py` 空骨架（先放 1 个占位断言），跑通 run_all=27，确认测试基建可收集。→ 完成判定：run_all 全绿。

**P4-0 固定成本组件化**（依赖：抽取器先能进字段）
| 步 | 文件:函数 | 动作 | 完成判定 |
|----|-----------|------|----------|
| S4-0.1 | `src/router/param_extractor.py` | 新增关键词抽取 `utilities(水电)/packaging(包装)/commission(提成)/other_fixed(其他固定)`，要求「概念+数字+单位」才取值 | 单测：`"水电800包装260提成1000"` → 三字段就位 |
| S4-0.2 | `workflow_engine._fill_params` (~line 359-440) | 为 4 新字段加 `_set`（有值标`[用户]`否则不计入）；`monthly_labor = employee_count×avg_salary`（avg_salary 优先用户值） | 参数字典含 4 字段 |
| S4-0.3 | `workflow_engine._fill_params` line 437-454 | 用 **C1 伪代码**替换 `else` 分支：组件求和 `rent+labor+utilities+packaging+commission+other_fixed`（逐项`[用户]`）；显式总数与组件和差>1 → 标矛盾（不静默选）；组件全缺才用显式总数兜底或`[缺失]`，**绝不猜 rent+labor** | 单测：rent12000+labor8000+util800+pack260+comm1000 → `monthly_fixed_cost==22060` 且来源全`[用户]` |

**P4-1 单位变动成本**
| 步 | 文件:函数 | 动作 | 完成判定 |
|----|-----------|------|----------|
| S4-1.1 | `src/router/param_extractor.py` | 抽 `unit_variable_cost`（"每份成本12元"） | 单测：`"每份成本12元"`→`unit_variable_cost=12` |
| S4-1.2 | `workflow_engine._fill_params` line 343-357 | 分支加：有 `unit_variable_cost`+`price_per_unit` → `ratio=unit_var/price` 标`[推导]`；显式 ratio 仍优先于推导；行业默认最后 | 单测：unit12+price15→`ratio==0.80`(`[推导]`)；显式75%优先 |

**P4-2 营收派生修正**
| 步 | 文件:函数 | 动作 | 完成判定 |
|----|-----------|------|----------|
| S4-2.1 | `src/session_state.py` `merge_params` | 确认「最近一次显式 revenue」不被后续 price×traffic 覆盖 | 单测：先给 rev=20000，再给 price/traffic → 仍 20000 |
| S4-2.2 | `workflow_engine._fill_params` line 428-435 | 显式 `monthly_revenue` 优先且不被派生覆盖；仅缺失才 `price×traffic×30×(1+g)`，g 仅用户给才用 | 单测：显式2万 vs 派生1.8万 → 取2万`[用户]` |

**P4-5 跑道修正**（独立小，先做降风险）
| 步 | 文件:函数 | 动作 | 完成判定 |
|----|-----------|------|----------|
| S4-5.1 | `financial_calculator._calc_runway` (122-126) + `calculate_runway` (403-435) | `current_cash is None`→返回`[缺失]`不算；`net_burn>0` 且 cash 有值 → 有限跑道；仅 `net_burn<=0` 才"无限" | — |
| S4-5.2 | `workflow_engine._safe_runway`/`_runway_numeric` | 确认把正确 `current_cash`(=available_cash) 与 `monthly_burn_rate` 传入 | 单测：profit=-8000,cash=80000→`runway≈10`；cash 缺失→`[缺失]` |

**P4-4 抽取器防误抓**
| 步 | 文件:函数 | 动作 | 完成判定 |
|----|-----------|------|----------|
| S4-4.1 | `src/router/param_extractor.py` | `monthly_expense/固定成本` 类关键词要求「概念+数字+单位」；问句/修辞（"是不是""每一项都给你了"）语境抑制取值 | 单测：`extract("…我把月固定成本每一项都给你了…")` 不产 `monthly_fixed_cost`(或≠1.0) |

**P4-3 路由收口**
| 步 | 文件:函数 | 动作 | 完成判定 |
|----|-----------|------|----------|
| S4-3.1 | `src/router/intent.py` | what-if/对比/保本问句归入引擎意图（不落 chitchat/自由 agent） | 单测：`"减租好还是提价好"`→引擎意图 |
| S4-3.2 | `web_server.py` | 删业务路径 `get_agent()`；what-if→`compare_scenarios`，保本→`breakeven`；LLM 仅 `llm_advisor.advise` | `grep get_agent` 业务路径无命中 |

**P4-7 LLM 引擎管理者（Engine Steward）**
| 步 | 文件:函数 | 动作 | 完成判定 |
|----|-----------|------|----------|
| S4-7.1 | `llm_advisor.advise` | 扩签名 `advise(scan, session_snapshot, user_text="")`；三入参 `copy.deepcopy` 只读，函数体无写引用、无算术表达式 | 入参为只读快照 |
| S4-7.2 | `llm_advisor` prompt | 升级为 Engine Steward：对账(发现矛盾→提问)、单一最高杠杆、最多一个下一步、冷静默认；**任何数字必来自 scan** | 输出结构符合 |
| S4-7.3 | `llm_advisor.advise` | what-if 需要数时**只调**引擎 `compare_scenarios`/`_calc_breakeven` 回填，绝不自算 | 单测：减租vs提价→有 compare 结果 |
| S4-7.4 | `llm_advisor` | 异常以结构化 `AnomalyReport`(描述+建议补丁+应覆盖测试)输出到日志，绝不 exec/eval/写文件 | 检测到 fixed=1.0 类 bug→产 report 不改数据 |
| S4-7.5 | `web_server.py` 调用处 | 传入 `session_snapshot`（SessionState 快照） | 调用链通 |

**P4-6 集成回归 oracle**（最后做，锁行为）
| 步 | 文件 | 动作 | 完成判定 |
|----|------|------|----------|
| S4-6.1 | `tests/test_phase4_workbench.py` | 落地 (d) 节 12 轮 oracle 全部断言（T1~T14） | ≥12 用例 |
| S4-6.2 | — | `tests/run_all.py` 全绿（26+新增≥12）；手动重放 12 轮逐轮对齐 | Phase 4 DoD 达成 |

**推荐施工顺序（依赖最优）**：
```
S4-0(准备) → P4-0(0.1→0.2→0.3) → P4-1 → P4-2 → P4-5 → P4-4 → P4-3 → P4-7 → P4-6(集成回归)
```
理由：抽取器字段(P4-0.1/P4-1.1/P4-4)是引擎聚合的前置；P4-5 独立可先降风险；路由收口(P4-3)与 LLM(P4-7)依赖前面引擎已能出正确数；P4-6 集成回归压轴锁全局行为。每完成一个 P4-x 立即 `run_all` 回归，红则停在本步不推进。

---

## 2. 决策已锁定（2026-07-09 用户拍板）

- **决策 A — 默认人力策略**：采用 **①③ 组合**（零默认兜底 + 模板假设前置可见可编辑）。未知人力按 0 计（诚实不虚高），同时把"假设值"渲染成"人工：未提供，当前按 0 计，可填写"的可见可编辑形态。
- **决策 B — 门禁严格度标准**：
  - **拦**：仅给租金（核心营收路径缺失）→ 返回"参数不足"骨架，不输出仪表盘/危险判定。
  - **放**：给租金 + 营收 → 出利润，但人工缺失时固定成本**不含虚构人工**、标 `[缺失]`；总投资缺失时**跑道仍标 `[缺失]` 不计算**（不因此误报危险）。
- **Phase 2（LLM 协作层）：已落地（轻量、被动、只读形态）**。用户最终选择「真正接 LLM 协作」——复用项目已有的 DeepSeek 通道（`src/agents/agent.py` 配置 + `DEEPSEEK_API_KEY`），新增 `src/llm_advisor.py` 做「基于结构化输出的解读」，而非让 LLM 接管工具编排（即未采用智能体形态，保留护栏）。

- **决策 C — 成本聚合契约（C1）**：固定成本组件（租金/人工/水电/包装/提成/其他）若用户给齐，引擎**自动求和**得 `monthly_fixed_cost`；仅当用户显式给总数但组件不全时以显式总数为兜底。用户不必手算总数。
- **决策 D — 营收派生契约（C2）**：`monthly_revenue` 以「最近一次用户显式给出的」为准；仅缺失时用 `日客流×客单价×(30或growth)` 派生，显式值不被派生覆盖。
- **决策 E — LLM 护栏契约（C3）**：LLM-worker 是「引擎管理者」而非「自由计算器」——对引擎只读数据(读取状态/结果，绝不改参数/SessionState/计算结果)、可运维(调度计算/调设置/提议代码修复)；**任何面向用户的数字必来自引擎结构化输出**。数据只来自用户原始输入(经抽取器)或引擎确定性推导(C1/C2)，LLM 永不直接写数据。此为「引擎=工作台、LLM=内置引擎管理者」北极星的硬约束（2026-07-10 由用户提出的「管理者」定位收敛而来）。

> **实施状态（2026-07-09）**：
> - **Phase 0 已全部落地并通过验证**：改动 `workflow_engine.py` + `formatter.py`，新增 `tests/test_quick_scan_phase0.py`。原 `8000→20000/0.0` 误报已消除。
> - **Phase 1 已落地并通过验证**：新增 `_fill_and_assess`(④) / `_build_scenarios`(③) / `_build_narrative`(⑤)，通用 band 驱动情景(⑥-lite)；trend/compare 接入共享态；formatter 新增「风险聚焦」+「情景分析」块。新增 `tests/test_phase1_flexibility.py`（7 用例全过，可独立运行）。租金+营收场景现输出"月利润 22000（乐观 26000/保守 6000）+ 风险聚焦在人工成本假设"而非单一死答案。
> - **Phase 2（LLM 协作层）已落地**：新增 `src/llm_advisor.py`（`_build_brief` 压简报 + `advise` 调 DeepSeek 解读）；`web_server.py` 业务路径在 `format_response` 后被动附「💡 AI 解读」。护栏：只读、不调工具、失败/无 key 返回空不阻断。真实 LLM 调用已验证通过；新增 `tests/test_phase2_llm_advisor.py`（4 用例）。当前 `tests/run_all.py` 共 **14 用例全过**。
> - **测试基建已跑通**：`.venv` 为 uv 纯净 venv（无 pip/pytest），故测试写成「可独立运行 + 可被 pytest 收集」双形态；新增 `tests/run_all.py` 统一入口，`.venv/bin/python3 tests/run_all.py` 跑通 **10/10 用例**（Phase 0 三例 + Phase 1 七例）。详见 `ARCHITECTURE.md`。
> - **Phase 3（跨轮对齐层）已落地**：基于用户实测对话暴露的「上下文缺失+数据对齐错误」诊断，新增 `src/session_state.py`（唯一真相源）+ 抽取器修复 + LLM 接地约束，方案已写入上方 Phase 3 章节并通过回归。羊肉汤店两轮对话：Turn1 抽成 `industry=餐饮, rent=12000, investment=200000, price=15, revenue=20000`（旧：rent=1.0 / investment 漏抓 / industry=None）；Turn2 自动 merge 出完整仪表盘（人工2人8000 + 固定2500 + 租金12000），**不再报「信息不全」、不进自由 agent 编造**。新增 `tests/test_phase3_session_alignment.py`（12 用例）。当前 `tests/run_all.py` 共 **26 用例全过**（Phase0 三 + Phase1 七 + Phase2 四 + Phase3 十二；含热修 2 例回归）。

---

## 3. 验收标准

1. `{monthly_rent:8000}` → 不再出现"月亏 2 万 / 危险"，改为"参数不足：还差 月营收 / 总投资 / 人工"。
2. `available_cash` 缺失时不参与跑道计算。
3. 人工成本不再静默用 6000（除非用户/模板显式提供，且可见、可改）。
4. 系统体量可控：Phase 0 不引入新依赖、不新增模板规则，保持"薄引擎"。

---

## 4. 执行顺序建议

```
Phase 0 → 决策A/B → Phase 1 → Phase 2(LLM协作) → Phase 3(跨轮对齐) → Phase 4(工作台一体化: 引擎补全+路由收口+防误抓) → Phase 5(what-if/compare) → 数据基础层(P0') → L2 决策引擎
```
- Phase 0/1/2 已全部完成、测试 14/14 通过。
- Phase 3（跨轮对齐层）已按 **P3-0 → P3-1 → P3-2** 顺序实施并通过羊肉汤店对话回归，当前全量测试 **26/26 通过**（含热修 2 例）。
- **Phase 4 / Phase 5 为计划态（2026-07-09 晚新增）**：基于用户 12 轮羊肉汤店对话暴露的「成本模型残缺 + 双脑子」根因，已锁定 C1/C2/C3 三条协作契约（决策 C/D/E）。待确认后按 **P4-0 → P4-5 → P4-6(回归) → P4-7(LLM角色) → P5-0→P5-2** 顺序实施。
- **数据基础层 + L2 决策引擎（2026-08-06 落地）**：取消「输入伪造型默认」（D2）+ basis 三分档 + 假设确认流 + 六类决策引擎（规则排序、无倾向、缺关键→还不能定）。全量测试 **218/218 通过**（含 `test_hypothesis_layer.py` 7 例、`test_decision_engine.py` 10 例）。视角收窄为「决策层到 L2，不做经营层 L3」，见 `~/productivity/projects/shangzhu-l2-decision-layer.md`。
