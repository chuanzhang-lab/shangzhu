# 模拟器升级计划 — shangzhu 2

> ## ⚠️ 实施状态（2026-09-12 标注）
>
> | 项 | 状态 |
> |---|---|
> | S1 用户指定多期收入序列 | ✅ 已落地（`revenue_series`） |
> | S2 NPV/IRR 接入仪表盘 | ✅ 已落地 |
> | S3 动态跑道 | ✅ 已落地 |
> | **S4 参数阶梯依赖** | ❌ **已回滚**（提交 `e4e4900`）——违反 `CALCULATION_PHILOSOPHY.md` 的「A 类字段绝不虚构」，且产出 `[阶梯]` 属「来源标注六义」之外的第七种标记 |
> | S5 多期场景对比 | ✅ 已落地 |
>
> **本文档第 142~200 行（P1-1 参数阶梯依赖）描述的设计已作废**，`config/step_rules.yaml` 已删除。
> 保留原文仅为决策留痕；请勿按该节实施。

## 一、现状调查结论

### 1.1 引擎已具备的能力（用户分析中被低估）

| 能力 | 现状 | 位置 |
|------|------|------|
| **NPV/IRR** | ✅ 已实现（Newton-Raphson 求解） | `financial_calculator.py:21-41` `calculate_npv` tool |
| **场景对比** | ✅ 已实现（双方案并排+差值+判定） | `workflow_engine.py:1255-1367` `compare_scenarios` tool |
| **12 月趋势** | ✅ 已实现（增长率+季节因子+累计利润+回本月） | `workflow_engine.py:696-760` `_project_trend_12m` |
| **现金流明细** | ✅ 已实现（逐月 inflow/outflow/缺口/到账延迟/季度租金） | `financial_calculator.py:200-300` `_calc_cashflow_schedule` |
| **保本分析** | ✅ 已实现（客单价口径+营收口径双路） | `financial_calculator.py:97-113` `_calc_breakeven` |
| **敏感性分析** | ✅ 已实现（营收×成本双轴扰动） | `financial_calculator.py:170-197` `_calc_sensitivity` |

### 1.2 引擎真正缺失的能力

| 缺失 | 严重度 | 说明 |
|------|--------|------|
| **用户指定多期收入序列** | P0 | 当前只支持 `growth_rate` 线性推算，不支持 `[30000, 45000, 60000]` 显式序列 |
| **NPV/IRR 未接入主仪表盘** | P0 | NPV/IRR 是独立 tool，quick_scan 输出中没有 |
| **动态跑道** | P0 | 跑道是静态单期（cash÷burn），未考虑增长趋势下的动态耗尽 |
| **参数阶梯依赖** | P1 | 员工数/租金不随营收变化，现实中是阶梯联动的 |
| **多期场景对比** | P1 | compare_scenarios 只比单期快照，不比趋势曲线 |
| **breakeven_month 接入仪表盘** | P1 | `_project_trend_12m` 已算出但 quick_scan 没用 |

### 1.3 技术栈

- Python 3.12 + uv venv
- FastAPI + LangChain tools
- 12 个行业模板（YAML 配置）
- 31 个测试文件，全部通过

## 二、改进范围与边界

### 范围内
- `src/tools/financial_calculator.py` — 新增函数
- `src/tools/workflow_engine.py` — 扩展 quick_scan / trend 输出
- `src/field_model.py` — 新增阶梯依赖规则（如需要）
- `tests/` — 新增测试

### 范围外
- 前端改动（本轮不做）
- LLM 提示词改动
- 数据库/存储层
- web_server.py 路由改动

## 三、改进设计

### P0-1：支持用户指定多期收入序列

**现状**：`monthly_revenue` 是单值，`_project_trend_12m` 用 `base_revenue * (1+growth)^n` 推算。

**设计**：支持 `monthly_revenue` 为数组，覆盖增长推算。

```python
# 用户输入：
params = {
    "monthly_revenue": [30000, 45000, 60000, 75000, 90000],  # 5 个月
    # 或者：
    "revenue": 30000,
    "growth_rate_monthly": 0.15,
    "projection_months": 12,
}

# _project_trend_12m 改造：
def _project_trend_12m(params: dict) -> dict:
    revenue_series = params.get("monthly_revenue")
    if isinstance(revenue_series, list):
        # 用户指定序列，直接用
        months_count = len(revenue_series)
    else:
        # 原逻辑：growth_rate 推算
        months_count = params.get("analysis_months") or 12
```

**改动文件**：
- `workflow_engine.py`：`_project_trend_12m` 支持数组输入
- `workflow_engine.py`：`_fill_params` 解析数组型 `monthly_revenue`
- `router/param_extractor.py`：识别 "前3个月3万后3个月5万" 类自然语言

**验收**：`monthly_revenue: [30000, 45000, 60000]` 输出 3 期逐月数据，breakeven_month 精确。

### P0-2：NPV/IRR 接入 quick_scan 仪表盘

**现状**：`calculate_npv` 是独立 tool，quick_scan 不输出 NPV/IRR。

**设计**：quick_scan 输出中新增 `investment_metrics` 块。

```python
# 在 quick_scan 的 dashboard 中新增：
from tools.financial_calculator import _npv_raw, _irr_raw

# 用 trend 数据构建现金流序列
if params.get("total_investment") and trend_data:
    cashflows = [-params["total_investment"]]
    cashflows += [m["profit"] for m in trend_data["months"]]
    npv = _npv_raw(0.08, cashflows)  # 默认 8% 折现率
    irr = _irr_raw(cashflows)
    dashboard["investment_metrics"] = {
        "npv_8pct": round(npv, 0),
        "irr": f"{irr*100:.1f}%" if irr else "无法收敛",
        "payback_months": trend_data["summary"]["months_to_breakeven"],
        "discount_rate": "8%",
    }
```

**改动文件**：
- `workflow_engine.py`：quick_scan 函数末尾追加 investment_metrics 计算

**验收**：quick_scan 输出含 `investment_metrics.npv_8pct` 和 `investment_metrics.irr`。

### P0-3：动态跑道（趋势感知）

**现状**：跑道 = `available_cash ÷ net_burn`，静态单期。

**设计**：用 trend 数据逐月扣减，找到现金耗尽月。

```python
# 在 quick_scan 中，已有 trend 数据时：
if params.get("available_cash") is not None and trend_data:
    cash = params["available_cash"]
    for m in trend_data["months"]:
        cash += m["profit"]
        if cash <= 0:
            dynamic_runway = m["month"]
            break
    else:
        dynamic_runway = ">" + str(len(trend_data["months"]))
    dashboard["core_metrics"]["runway_dynamic"] = dynamic_runway
    dashboard["core_metrics"]["max_cash_gap"] = min(
        (params["available_cash"] + sum(m["profit"] for m in trend_data["months"][:i+1])
         for i in range(len(trend_data["months"]))),
    )
```

**改动文件**：
- `workflow_engine.py`：quick_scan 追加 runway_dynamic 和 max_cash_gap

**验收**：quick_scan 输出含 `runway_dynamic`（精确到月）和 `max_cash_gap`（最低现金点）。

### P1-1：参数阶梯依赖

**现状**：参数孤立，员工数涨 10 倍租金不变。

**设计**：在 `_fill_params` 后追加阶梯规则引擎。

```python
# config/step_rules.yaml（新增配置文件）
step_rules:
  employee_count:
    - trigger: monthly_revenue
      ranges:
        - {min: 0, max: 50000, value: 2}
        - {min: 50000, max: 100000, value: 3}
        - {min: 100000, max: 200000, value: 5}
        - {min: 200000, value: 8}
  monthly_rent:
    - trigger: employee_count
      ranges:
        - {min: 0, max: 5, value: 5000}
        - {min: 5, max: 8, value: 8000}
        - {min: 8, value: 12000}

# workflow_engine.py 新增：
def _apply_step_rules(params: dict, src: dict) -> dict:
    """应用阶梯依赖规则，返回修改后的 params + src 标注。"""
    rules = _load_step_rules()
    changed = True
    iterations = 0
    while changed and iterations < 5:  # 防循环
        changed = False
        iterations += 1
        for field, rule_list in rules.items():
            if src.get(field, "").startswith("[用户]"):
                continue  # 用户显式值不覆盖
            for rule in rule_list:
                trigger_val = params.get(rule["trigger"])
                if trigger_val is None:
                    continue
                for r in rule["ranges"]:
                    if r.get("min", 0) <= trigger_val < r.get("max", float("inf")):
                        if params.get(field) != r["value"]:
                            params[field] = r["value"]
                            src[field] = f"[阶梯] {rule['trigger']}={trigger_val:g} → {field}={r['value']}"
                            changed = True
                        break
    return params, src
```

**改动文件**：
- `config/step_rules.yaml`（新增）
- `workflow_engine.py`：`_fill_and_assess` 中调用 `_apply_step_rules`

**验收**：`monthly_revenue=120000` 时 `employee_count` 自动升为 5，`monthly_rent` 自动升为 8000。

### P1-2：多期场景对比

**现状**：`compare_scenarios` 只比单期快照。

**设计**：新增 `compare_trends` 函数，对比两个方案的 12 月趋势。

```python
def compare_trends(base_params: dict, alt_params: dict) -> dict:
    """对比两个方案的 12 月趋势曲线。"""
    base_trend = _project_trend_12m(base_params)
    alt_trend = _project_trend_12m(alt_params)
    return {
        "base": base_trend["summary"],
        "alt": alt_trend["summary"],
        "diff": {
            "annual_profit": alt_trend["summary"]["total_annual_profit"] - base_trend["summary"]["total_annual_profit"],
            "breakeven_delta": (alt_trend["summary"]["months_to_breakeven"] or 99) - (base_trend["summary"]["months_to_breakeven"] or 99),
        },
        "base_months": base_trend["months"],
        "alt_months": alt_trend["months"],
    }
```

**改动文件**：
- `workflow_engine.py`：新增 `compare_trends` 函数
- `workflow_engine.py`：`compare_scenarios` tool 追加 `trends` 字段

**验收**：compare_scenarios 输出含两个方案的 12 月趋势对比。

## 四、实施步骤

| 步骤 | 目标 | 改动文件 | 验收标准 |
|------|------|---------|---------|
| S1 | P0-1 支持收入序列 | workflow_engine.py | `monthly_revenue: [30000, 45000]` 输出 2 期趋势 |
| S2 | P0-2 NPV/IRR 接入 | workflow_engine.py | quick_scan 含 investment_metrics |
| S3 | P0-3 动态跑道 | workflow_engine.py | quick_scan 含 runway_dynamic |
| S4 | P1-1 阶梯依赖 | workflow_engine.py + config/ | revenue=120k → employee=5 |
| S5 | P1-2 多期对比 | workflow_engine.py | compare_scenarios 含 trends |
| S6 | 测试 | tests/ | 全量回归通过 |

## 五、风险

| 风险 | 影响 | 应对 |
|------|------|------|
| 阶梯规则循环依赖 | 死循环 | max 5 次迭代 + 变化检测 |
| IRR 不收敛 | 返回 None | 已有 max_iter=1000 + tol=1e-7 |
| 收入序列长度不一致 | 计算错误 | 以最短序列为准，剩余按最后值填充 |
| 现有测试回归 | 功能退化 | 每步独立验证+全量回归 |
