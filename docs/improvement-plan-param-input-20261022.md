# 参数输入层重构完整改进计划（修订版 · 基线已校正）

- 日期：2026-10-22
- 目标仓：**shangzhu（中文仓）** @ `0f15339`（版本 0.3.0）——线上实际部署的就是这个仓
- 依据：code-improvement-plan 六阶段流程 + fix-protocol 修复协议
- 触发：2026-10-03/04 线上事故——「客人 80」被记成「员工 80 人」、多轮补参后参数静默丢失、覆盖率跌到 17%

> **基线校正说明**：本计划的前身曾误把目标定为 shangzhu-en 仓。2026-10-22 以线上界面代码核实后确认：部署站点 `shangzhu-en.app.workbuddy.host`（hostname 里的 "en" 是 workbuddy 应用槽位名）跑的是**中文仓 shangzhu @ 0f15339**。
> 判定证据：线上 /i18n.js = 404、app.js 无 `function t(`、HTML 为 `lang="zh-CN"` 硬编码、无 `__T[` 占位符；线上 app.js sha256 前 16 位 `915d27335d71f90f` 与中文仓 `720bf5d..0f15339` 区间逐字节一致；线上 /health 报 `version 0.3.0` 与中文仓 pyproject 一致。

---

## 1. 背景与目标

- **项目概述**：创业者财务建模工作台。规则引擎优先（意图/抽取/计算全确定性代码），LLM 仅做解读（Engine Steward，只读）。前端原生 JS 单页 + 右侧参数面板；后端 FastAPI + SessionState + PG/JSON/memory 多档存储。
- **本次目标**：把「参数输入层」从「自然语言必经之路」重构为「结构化表单主输入 + NL 可选快捷 + 确认层」，使命中理解层的 bug 类不再无声进引擎：
  1. 新增结构化参数写入口（PUT /tasks/{id}/params），成为唯一写入口；
  2. 右侧面板升级为完整表单（全字段、分组、行业模板预填、派生只读区）；
  3. NL 抽取结果经表单确认才进引擎；
  4. 修复已实证的两处真 bug（见问题清单 P-02/P-03）与一处部署形态缺陷（P-01）。
- **范围一句话**：只改参数输入层；计算引擎（field_model/workflow_engine/param_guard）零语义改动。

## 2. 现状总结（全部实测）

### 2.1 代码现状

| 项 | 实测结果 |
|---|---|
| 规模 | web_server.py（~1700 行，含 CHAT_HTML）+ src/（router 抽取/意图、session_state、param_guard、field_model、llm_advisor、tools）+ src/web_static/app.js（~1300 行）+ config/（industry_templates.yaml 12 行业、decision_policy.yaml） |
| 测试 | 541 用例（60 文件）；tests/conftest.py 存在（测试库隔离已建）；**无 p2a 语料正确性断言** |
| 参数写入 | **仅 /chat 一条 NL 路径**。全仓无 PUT params 端点 |
| 右侧面板 | 双层：`updateParamsPanel` 只读展示（只渲染**已有值**字段）+ `renderParamFields` 改参区（7 字段，同样只渲染已有值） |
| 改参提交 | **假表单 round-trip**：pcRecalc 把表单值合成 NL 句子（"把月租金改成8000"）→ send() → 抽取器再解析回结构化 |
| 可用资产 | `src/field_model.py` 已有 INPUT_SPECS/DERIVED_SPECS + derive() 拓扑求值器；`session_state.PARAM_GROUPS` 已有语义分组；industry_templates.yaml 已有 hypotheses 默认值 + benchmark 基准——**表单 schema 的全部数据源已存在** |
| Git | HEAD `0f15339`，工作区仅未跟踪 `.zcodeignore` |

### 2.2 环境现状

| 项 | 实测结果 |
|---|---|
| 运行时 | .venv Python 3.12；node v26（ESLint/playwright 已配） |
| 部署 | workbuddy 托管；演示实例显式配 `STORE_BACKEND=memory`（README 声明「内存档演示实例」）；最新备份 20261008（陈旧 14 天） |
| 存储多档 | pg / file / memory 三档，由 STORE_BACKEND 环境变量选择 |

### 2.3 探针实证结论（2026-10-22 跑通，脚本见 ~/.hermes/cache/scratch/probe_zh_extract.py）

**① 代码层无跨轮丢失 bug。** 五轮对话在单进程 + file store 下完整累积（price→employee→客人→50人/天→分析，落库与内存 session 全程齐全），merge/hydrate/persist 链路正常。

**② 线上丢失 = 部署形态。** 复刻线上（uvicorn `--workers 2` + `STORE_BACKEND=memory`）：前三轮正常累积，**第 4 轮「分析」params 为空**——请求轮询到未见过历史轮次的 worker，其 MemoryStore/SessionState 均为空。线上「部分字段丢失 + 覆盖率 17%」正是各 worker 见到不同轮次子集的表现。

**③ 「员工80」是真代码 bug。** `客人80人` → `employee_count=80`；`50人/天` → `daily_traffic=50` **且** `employee_count=50` 双写。`_HEADCOUNT_RE` 负向断言只挡「均/次/创」，未挡「/天」等后置语境，导致任何「N人」形态无差别进员工数，且误抽值会覆盖真值（探针中 employee 80 被 50 覆盖）。

## 3. 问题清单

| 编号 | 严重度 | 现象 | 位置 | 影响 |
|------|--------|------|------|------|
| P-01 | 严重 | 演示实例 STORE_BACKEND=memory 且多 worker，会话参数被轮询打散 | 部署配置（非代码缺陷，代码层已证无罪） | 用户补的参数下一轮可能消失，分析结果错误 |
| P-02 | 严重 | 「N人」形态无差别进 employee_count（客人80人→员工80；50人/天→员工+客流双写），且误抽值覆盖真值 | src/router/param_extractor.py `_HEADCOUNT_RE` / `_extract_headcount` | 静默错值入 session，比漏抽更危险 |
| P-03 | 严重 | 参数写入仅 NL 一条路径，理解层错误直接进引擎 | web_server.py /chat；无 PUT params 端点 | 同类误抽无可绕过通道 |
| P-04 | 一般 | 改参假表单 round-trip（结构化→NL 句子→再解析） | app.js pcRecalc | 为已结构化数据白付理解成本；补丁叠床架屋 |
| P-05 | 一般 | 表单只渲染已有值字段，无法补从未输入的字段 | app.js renderParamFields | 用户只能回 NL 独木桥 |
| P-06 | 一般 | 模板库（12 行业默认值+基准）无预填入口 | industry_templates.yaml 仅被引擎消费 | 模板价值依赖 NL 命中运气 |
| P-07 | 轻微 | `.zcodeignore` 等工具产物未 gitignore | .gitignore | 仓洁度 |

## 4. 改进范围与目标

**要做的 8 项**：① 部署形态修复 + 启动告警；② 抽取器三修 + 两面用例固化；③ PUT /tasks/{id}/params；④ GET /form-schema；⑤ 前端完整表单；⑥ 改参切结构化 + 模板预填；⑦ NL 确认层；⑧ 收尾（gitignore/文档/灰度开关）。

**完成标准**：演示实例不再丢上下文；表单可补全部输入字段且提交不过理解层；NL 结果经确认才进引擎；全量测试 + e2e + 负向探针全绿；P-01~P-07 逐条关闭。

**明确不做**：不重写抽取器（词表/兜底定点修）；不引入 LLM 规整层（确认层见效前不立项）；不动计算引擎语义；不做多端/账号体系；不合并 EN 仓（另案）。

## 5. 项目边界声明

- **范围内**：`/Users/newmacbook/Desktop/shangzhu/` 全部代码、配置、测试、文档。
- **范围外（不涉及）**：
  - `/Users/newmacbook/Desktop/shangyezhushou/shangzhu-en/`——仅结构参照，零修改；双仓同步另案；
  - workbuddy 平台本身（只消费其 ENV 配置，不改平台设置）；
  - 本机 PG/系统环境（仅以连接配置声明）。
- 依据：boundary-rules.md。

## 6. 改进设计（十维度）

### 6.1 架构设计
三层输入、一个写入口、单向数据流：
```
① 结构化表单（主）┐
② NL 快捷输入    ┼→ PUT /tasks/{id}/params（唯一写入口）→ apply_turn_guarded → SessionState → 落库
③ NL 确认层      ┘   （merge/guard/锁/_persist_turn 全部原样复用，禁止新写更新路径）
```
理解层（extract_params）从必经之路降级为 ②③ 的可选前置；表单值**永不** round-trip 成文本。

### 6.2 功能设计
1. **完整表单**：INPUT_SPECS 全字段常驻，按 PARAM_GROUPS 分节折叠；三态来源标（[用户]/[默认]/[缺失]）；DERIVED_SPECS 派生字段只读区；
2. **行业模板预填**：选行业 → hypotheses 预填（标 [默认]）+ benchmark 参考列；「重置为模板默认」按节操作；
3. **PUT 端点**：全量/增量 params → apply_turn_guarded → quick_scan 重算 → 返回 {scan, derived, param_sources, guard}；
4. **GET /form-schema**：投影 INPUT_SPECS + DERIVED_SPECS + PARAM_GROUPS + 模板默认值 + i18n 键名；
5. **NL 确认层**：抽取结果先呈现为表单值，确认才提交（前端流程，落点仍是 PUT）；可设置跳过；
6. **空态引导**：新任务提示选行业，保留 EMPTY_STATE 示例卡作 NL 快捷入口。

### 6.3 数据设计
- **Schema 单源**：不发明新 schema，/form-schema 投影 field_model.INPUT_SPECS/DERIVED_SPECS + PARAM_GROUPS + industry_templates.yaml；加字段改 field_model 一处；
- **params 存储不变**（task.params JSONB/JSON）；模板预填值用新增来源码 `[default]`，与现有四来源体系（user/default/derived/missing）打通。

### 6.4 接口设计
```
PUT /tasks/{task_id}/params
  Headers: X-Requested-With: XMLHttpRequest（复用现有 CSRF 中间件，不豁免）
  Body: {"params": {"daily_traffic": 80, "price_per_unit": 18}}
  200: {"ok": true, "params": {...}, "scan": {...}, "derived": [...], "param_sources": {...}, "guard": {...}}
  400/403/404：白名单外字段/缺 XHR 头/任务不存在
GET /form-schema
  200: {"groups": [...], "fields": {...}, "derived": {...}, "templates": {...}}
```
内部复用：apply_turn_guarded（merge+guard+锁）、quick_scan_tool、_persist_turn、get_biz_snapshot。

### 6.5 性能设计
schema 启动时构建一次并进程内缓存；PUT 与 /chat 共用 SessionState._LOCK，无新竞态；PUT 走 asyncio.to_thread；派生值提交时算（关键字段防抖是 M-06 可选项）。

### 6.6 安全设计
PUT 走 X-Requested-With 中间件不豁免；字段白名单 + 类型/范围校验全走现有 param_guard，不另写校验；前端 number 输入拒绝 NaN；无新密钥面。

### 6.7 可维护性设计
表单渲染 schema 驱动（加字段改 YAML/field_model，前端零改）；**净减代码**——pcRecalc 的 NL 合成 + F4 改动检测补丁随 round-trip 退役；修改点注明事故溯源注释（沿用项目 F 编号注释文化）。

### 6.8 可靠性设计
PUT 幂等（全量语义）；guard 矛盾照旧拦截并在表单高亮；**多 worker + memory 组合在启动时打 WARNING**（防 P-01 复发）；hydrate 失败从静默丢变表单空态可见。

### 6.9 可测试性设计
- **P-02 两面用例**（必须同时绿）：`请两个人`→employee_count=2 仍成立；`50人/天`→仅 daily_traffic，不得进 employee_count；`客人80人`→daily_traffic 或空，不得进 employee_count；`员工80人`→employee_count=80 仍成立；
- PUT 契约测试：白名单/merge 语义/guard 拦截/持久化/XHR 403/404；
- schema 端点：下发与 field_model 一致、模板默认值齐全；
- 探针脚本注入版：五轮对话在 file 模式完整累积、在 memory+多 worker 模式复现丢失（转 while deploying-aware）；
- e2e：填表提交→分析→断言派生值。

### 6.10 兼容与部署设计
灰度：新表单 behind 设置开关（默认开），旧改参流保留一版，M-06 后删；部署形态修复随 When/WORKERS 配置；每模块独立 commit 可回滚；/chat 路径始终可用作兜底。

## 7. 流程模块拆解

| 模块 | 目标 | 前置 | 具体动作 | 验收标准 | 回退 |
|------|------|------|---------|---------|------|
| M-01 | 部署形态修复（上下文丢失） | 无 | 演示实例改为单 worker（或换 file/pg 存储）；代码侧：`STORE_BACKEND=memory` 且 worker>1 时启动打 WARNING | 演示站跑五轮对话不再丢参数；本地 uvicorn 双 worker 启动时可见 WARNING | revert commit / 改回 ENV |
| M-02 | 抽取器三修 | 无 | `_HEADCOUNT_RE` 补后置语境断言（/天、每人、每次、来、消费…）；客人/顾客/来客/主顾进 daily_traffic 关键词；「N人/天」等语境禁双写（客流优先于员工数） | 6.9 两面用例全绿；541+ 全量测试不回归；探针脚本误抽项转空/正确 | revert commit |
| M-03 | PUT /tasks/{id}/params | M-01 | 新路由复用 apply_turn_guarded；契约测试 | 契约测试绿；curl 实测 200/400/403/404；旧字段 merge 保留 | revert |
| M-04 | GET /form-schema | M-03 | 投影 INPUT_SPECS/DERIVED_SPECS/PARAM_GROUPS/模板；进程内缓存 | 下发与 field_model 一致（测试断言） | revert |
| M-05 | 前端完整表单 | M-04 | app.js schema 驱动渲染全字段分节；三态来源标；派生只读区；删除「只渲染已有值」逻辑 | 字段数 = INPUT_SPECS 输入字段数；缺参字段可填 | revert |
| M-06 | 改参切结构化 + 模板预填 | M-05 | pcRecalc 改调 PUT（删 NL 合成与 F4 补丁）；行业选择→预填+benchmark 参考列 | 网络面板只见 PUT；选行业后表单预填 | revert |
| M-07 | NL 确认层 | M-06 | 抽取结果 → 表单预填 +「确认开算」→ PUT；可设置跳过 | 不确认不进引擎；跳过开关生效 | revert |
| M-08 | 收尾 | M-07 | .gitignore 补 .zcodeignore/工具产物；README/AGENT.md 更新；灰度开关定稿 | 仓洁；文档齐；开关可关 | revert |

## 8. 实施步骤与里程碑

**顺序**：M-01 → M-02 → M-03 → M-04 → M-05 → M-06 → M-07 → M-08（M-01 与 M-02 可并行）

- **MS1 地基与止血**（M-01+M-02）：上下文不再丢失；误抽类封死并有两面用例锁定。
- **MS2 完整表单上线**（M-03+M-04+M-05+M-06）：表单成为主输入，理解层退出必经之路。
- **MS3 理解层降级为可选**（M-07+M-08）：NL 结果过确认层。

**关键路径**：M-02 → M-03 → M-05 → M-06 → M-07。

## 9. 风险与依赖

| 风险/依赖 | 类型 | 影响 | 应对 |
|----------|------|------|------|
| M-02 正则改反（误拦真实员工数或误放人流） | 技术 | 新旧 bug 叠加 | 两面用例 mandatory；先补测试（红）再改代码（绿） |
| 演示实例改 worker 数需动部署配置 | 外部 | M-01 延迟 | 若不可控，改换 file 存储同效；代码 WARNING 先落地 |
| 主交互改动影响面大 | 体验 | 习惯冲击 | 灰度开关 + 旧流保留一版 |
| PUT 与 /chat 双写 session | 技术 | 竞态 | 复用现有锁；契约测试含连续提交 |
| 表单信息密度（15+ 字段） | 体验 | 一屏放不下 | 分节折叠 + 模板预填降必填量 |

## 10. 验收标准

**总体**：演示站上下文不丢；表单可补全部字段且提交不过理解层；NL 结果确认才进引擎；全量测试 + e2e + 负向探针绿；P-01~P-07 关闭。

**分里程碑**：
- MS1：五轮 file 模式完整累积（探针 Parts 2 绿）；双 worker 启动见 WARNING；6.9 两面用例全绿；
- MS2：表单字段数 = INPUT_SPECS 输入字段数；模板预填标 [默认]；改参请求面板只见 PUT /tasks/{id}/params；
- MS3：抽取结果不确认不进引擎；跳过开关生效；全量 + e2e 绿。

**验收方式**：每模块命令实测留档；**负向验证 mandatory**——注入事故同形态缺陷（表单提交后参数丢失改封装版、客人80人再次误抽、PUT 绕过 XHR）必须门禁变红，再还原转绿。

## 11. 审计安排

- **时机**：MS3 完成后（或每里程碑阶段审计）。
- **六大维度**（audit-checklist.md）：错误纠正、逻辑修正（merge 语义/三态标/预填重置）、模块冲突专项（PUT 与 /chat 双写一致性、schema 与 field_model 同源、来源码新旧兼容）、运行改进（对照 2.2 环境差距）、功能边界（理解层不得回流进表单路径）、工程完整性（删 round-trip 后无死代码、依赖声明、文档测试）。
- **负向验证**：如前所述，三者必须见红再转绿。
- **产出**：`docs/audit-report-param-input-<date>.md`。
