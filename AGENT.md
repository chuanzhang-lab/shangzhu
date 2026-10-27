# 创业者商业建模工作台 v3 — 架构规范

## 架构分层

```
┌─────────────────────────────────────────────┐
│  框架层（稳定，不可变）                       │
│  · 计算公式：盈亏平衡、NPV、IRR、跑道等       │
│  · 输出结构：核心指标→参数→敏感性→风险→benchmark│
│  · 工具行为：quick_scan/trend/compare 职责固定 │
│  · 避坑规则：定价<成本、现金流<3月 必须警告    │
├─────────────────────────────────────────────┤
│  参考层（稳定但有弹性）                       │
│  · 行业基准值：12个行业默认参数，标注 [默认]   │
│  · benchmark：行业范围区间，非精确值           │
│  · 用户给够参数 → 跳过模板 → 标注 [自定义]    │
├─────────────────────────────────────────────┤
│  用户层（完全灵活）                           │
│  · 参数值：用户说了算，标注 [用户]             │
│  · 项目定义：用户命名，不强制归类              │
│  · 分析深度：快速/详细 由用户选择              │
│  · 输出偏好：表格/一句话/PDF 适应用户          │
└─────────────────────────────────────────────┘
```

## 数据模型

### 参数分类

| 类别 | 字段 | 来源优先级 |
|------|------|-----------|
| 财务 | total_investment, monthly_rent, monthly_expense, price_per_unit, variable_cost_ratio | 用户 > 行业默认 > 推算 |
| 收入 | daily_traffic, monthly_revenue, monthly_growth_rate | 用户 > 推算 |
| 团队 | employee_count, avg_salary, founder_count | 用户 > 行业默认 |
| 时间 | stage, analysis_months, seasonal_factor | 用户 > 默认 |
| 市场 | industry, city, target_market_size | 用户 > 空 |

### 参数来源标记

- `[用户]` — 用户明确提供
- `[默认]` — 行业模板填充
- `[推算]` — 从其他参数计算得出
- `[缺失]` — 未知。**不参与下游计算**（如跑道、风险判定），绝不当 0 处理

> 四义封闭：任何参数的来源只能是这四种之一，不得新增第五种标记（曾出现的 `[阶梯]`
> 因破坏封闭性已被回滚，见 `CALCULATION_PHILOSOPHY.md`）。

## 参数输入层（0.4.0 起）

三层输入、**一个写入口**、单向数据流：

```
① 结构化表单（主）┐
② NL 快捷输入    ┼→ PUT /tasks/{id}/params（唯一写入口）→ apply_turn_guarded → SessionState → 落库
③ NL 确认层      ┘   （merge/guard/锁/快照同步全部复用，禁止新写更新路径）
```

- **表单主输入**：`GET /form-schema` 驱动全字段分节（INPUT_SPECS 25 字段 + PARAM_GROUPS + 12 行业模板），前端 schema 驱动渲染，加字段只改 field_model 一处；
- **NL 确认层（默认开）**：/chat 抽取的参数以 `[待确认]` 草稿态进表单，用户点「确认开算」→ PUT 才进引擎；不确认不进引擎。`nl_confirm` 请求字段控制（缺省 None = 旧调用方走原合并路径，API 兼容；前端按「NL 免确认直接生效」设置显式发送）；
- **`[待确认]` 不破坏四义封闭**：它是前端草稿态，从不写入引擎 param_sources——引擎侧来源永远只有上述四种；
- **守门铁律**：任何新的参数写入需求必须走 `apply_turn_guarded`（`PUT` 端点与前端 `submitParams` 是它的仅有的两个调用面），历史上「另写一条简单更新路径」是本项目 bug 之源。

## 工具规范

### quick_scan
- 职责：接收参数 → 全量计算 → 返回完整仪表盘
- 输出：core_metrics + params + param_sources + sensitivity + pitfalls + benchmark
- 模板策略：用户给够5项核心参数 → 跳过模板；不够 → 最接近行业模板 + 标注

### trend_projection
- 职责：12个月趋势预测，含季节性因子
- 输出：月度数据 + 年度汇总 + 关键拐点

### compare_scenarios
- 职责：两个方案并排对比
- 输出：base_scenario + alt_scenario + diff + verdict

## 行为规范

1. 不问问题、不给建议、不评价参数
2. 参数标注来源（用户/默认/推算）
3. 用户给够参数 → 跳过模板 → 标注「自定义」
4. 混合业态 → 检测并警告 → 让用户确认
5. 分析深度由用户控制（快速/详细）

## 工程公约（2026-10-03 四层防线事故复盘，全体模块适用）

1. **降级必有痕**：任何 except 降级/回退路径必须 logger.warning/error 留痕
   （范本：storage 的 get_store 降级链）。静默降级 = 隐性故障。
2. **异常不吞**：catch-all 必须给出痕迹——后端 logger 留痕，前端走
   reportClientError（console `[失败于[阶段:错误码]]` + /client-log 上报）。
   口径与三档审计见 docs/except-audit-20261003.md。
3. **每事故一护栏**：每起事故复盘后固化一条护栏测试（命名 `test_*_guard` /
   `test_*_shadow`），把点状修复升级为面状规则。已有范例：
   test_appjs_shadow_guard（遮蔽）、test_static_cache_guard（缓存）、
   test_isolation_guard（测试隔离）、test_no_unawaited_async（无痕失败）、
   test_copy_drift_guard（双副本漂移）。
4. **备份必可校验、恢复必演练**（2026-10-07 存储加固）：任何「备份 / 导出」都要能当场
   验证（`pg_restore --list` 列得出目录才算数），恢复路径必须存在且跑过演练（`make drill`）。
   不可验证的备份 = 纸面承诺。
5. **降级必须让用户看得见**（2026-10-07）：只写日志不够——「当前哪个后端 / 落在哪 / 为什么」
   要同时进 `/health`（`store_*` 字段）与页面横幅。日志只有开发者看得到，而「我的数据现在
   落在哪」是用户必须知道的事。

## 排障口诀

先分清服务端还是前端：`logs/web_server.log`（服务端异常/降级/WEBCLIENT 前端上报）
→ 浏览器 console `[失败于[阶段:错误码]]` → 都干净则硬刷新（Cmd+Shift+R）排旧缓存，
或看「页面版本过旧」横幅。服务重启/升级后习惯性硬刷一次（start.sh 横幅有提示）。

存储相关：先跑 `.venv/bin/python3 scripts/doctor.py`（五层分辨 + 可粘贴修复命令）
→ 看页面顶部降级横幅 → `/health` 的 `store_backend` / `store_degraded` / `store_target` /
`store_orphan_tasks` / `store_write_failures` 是同一事实的机器可读版本。
PG 恢复后若曾降级过，记得 `scripts/migrate_json_to_pg.py` 把孤儿数据迁回。
