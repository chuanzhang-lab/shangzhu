"""声明式财务字段模型（Field Model）— P&L 主干公式的唯一出处。

设计目标（结构性重构，根治「公式散落/重复实现」）：
1. 每个「派生字段」只在此声明一次：公式、依赖、标签、单位、来源语义。
2. `derive()` 是通用求值器：给定「输入字段集」（含缺失 None），沿依赖拓扑
   把能精确推出的派生字段全部算出；缺依赖 → 该字段 missing。
3. `consistency_issues()` 声明「可互相校验的关系」（如月营收 vs 客流×单价），
   由求值后自动检查，死代码问题消失。
4. 应用层（workflow_engine / formatter / decision）一律消费模型，不再手写公式。

与「默认值」的分界：本模型只做**精确推导**（给够输入即出精确值），
绝不填任何猜测性默认——输入缺失即 missing，由上层决定如何呈现。

骨架完整性（D13 改进）：
- INPUT_SPECS：输入字段声明（label/unit/type/aliases），与 DERIVED_SPECS 统一
- derive()：始终尝试公式（不做 deps 硬门控），返回 (values, meta)
- monthly_fixed_cost：真公式（sum of present components）
- variable_cost_ratio：多路推导（user > unit_var÷price > 1−gm > None）
- _topo_order()：循环依赖检测
- 所有公式用 .get() 容错
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

# ── 输入字段声明 ─────────────────────────────────────────────────────────
# 用户可提供的字段：label/unit/type/aliases（aliases 是抽取器的别名列表）
INPUT_SPECS: Dict[str, Dict[str, Any]] = {
    "total_investment": {"label": "总投资", "unit": "元", "type": "float"},
    "monthly_rent": {"label": "月租金", "unit": "元/月", "type": "float"},
    "daily_traffic": {"label": "日均客流", "unit": "人/天", "type": "float"},
    "price_per_unit": {"label": "客单价", "unit": "元", "type": "float"},
    "employee_count": {"label": "员工人数", "unit": "人", "type": "float"},
    "avg_salary": {"label": "人均薪资", "unit": "元/月", "type": "float"},
    "labor_burden": {"label": "劳动负担率", "unit": "", "type": "float"},
    "variable_cost_ratio": {"label": "变动成本率", "unit": "0~1", "type": "float"},
    "unit_variable_cost": {"label": "单位变动成本", "unit": "元/单位", "type": "float"},
    # S3（2026-09-12）：统一为 0~1 口径 —— 与 param_guard 的归一化、
    # 与 variable_cost_ratio 的 "0~1" 对齐。旧声明 "%" 与公式里的 ÷100 自相矛盾，
    # 导致 derive({"gross_margin": 0.6}) 算出 vcr=0.994（应为 0.4）。
    "gross_margin": {"label": "毛利率", "unit": "0~1", "type": "float"},
    "utilities": {"label": "水电", "unit": "元/月", "type": "float"},
    "packaging": {"label": "包装", "unit": "元/月", "type": "float"},
    "commission": {"label": "提成", "unit": "元/月", "type": "float"},
    "other_fixed": {"label": "其他固定", "unit": "元/月", "type": "float"},
    "equipment_ratio": {"label": "设备占比", "unit": "0~1", "type": "float"},
    "monthly_revenue": {"label": "月营收", "unit": "元/月", "type": "float"},
    "monthly_profit": {"label": "月利润", "unit": "元/月", "type": "float"},
    "monthly_expense": {"label": "月固定成本（显式总数）", "unit": "元/月", "type": "float"},
    "stage": {"label": "阶段", "unit": "", "type": "str"},
    "industry": {"label": "行业", "unit": "", "type": "str"},
    "founder_count": {"label": "创始人数", "unit": "人", "type": "int"},
    "monthly_growth_rate": {"label": "月增长率", "unit": "0~1", "type": "float"},
    "seasonal_factor": {"label": "季节因子", "unit": "", "type": "float"},
    "analysis_months": {"label": "分析月数", "unit": "月", "type": "int"},
}

# ── 派生字段声明 ─────────────────────────────────────────────────────────
# 每个字段：
#   deps    : 依赖字段（用于拓扑排序，不用于硬门控）
#   formula : 计算公式（lambda params -> value；用 .get() 容错；返回 None 即 missing）
#   label   : 中文名
#   unit    : 单位
#   kind    : "derived"（纯公式推） | "override"（用户可覆盖，优先用用户值）
#   user_direct_ok: 是否允许显示「用户直接给出」（仅 monthly_revenue/monthly_profit）
#   describe: 返回「带实际数字的公式说明」字符串
#   _hidden : 中间量，不单独展示

DERIVED_SPECS: Dict[str, Dict[str, Any]] = {
    # 月营收：用户直接给 或 客流×单价×30
    "monthly_revenue": {
        "deps": ["daily_traffic", "price_per_unit"],
        "formula": lambda p: (p.get("daily_traffic") or 0) * (p.get("price_per_unit") or 0) * 30 or None,
        "label": "月营收", "unit": "元/月", "kind": "override", "user_direct_ok": True,
        "describe": lambda p: f"日均客流 {p.get('daily_traffic', 0):g} × 客单价 {p.get('price_per_unit', 0):g} × 30天",
    },
    # 变动成本率：多路推导（用户 > unit_var÷price > 1−gm > None）
    # S3：gm 为 0~1 口径，故此处是 `1 − gm`（不再是 `1 − gm/100`）。
    "variable_cost_ratio": {
        "deps": ["price_per_unit"],
        "formula": lambda p: (
            (p.get("unit_variable_cost") / p["price_per_unit"])
            if p.get("unit_variable_cost") is not None and p.get("price_per_unit")
            else (1 - p.get("gross_margin", 0))
            if p.get("gross_margin") is not None
            else None
        ),
        "label": "变动成本率", "unit": "0~1", "kind": "override", "user_direct_ok": True,
        "display_percent": True,   # 内部 0~1，展示为百分数
        "describe": lambda p: (
            f"单位变动成本 {p.get('unit_variable_cost', 0):g} ÷ 客单价 {p.get('price_per_unit', 0):g}"
            if p.get("unit_variable_cost") is not None
            else f"1 − 毛利率 {p.get('gross_margin', 0):.0%}"
            if p.get("gross_margin") is not None
            else "公式推导"
        ),
    },
    # 月人工现金：人数 × 人均薪资（中间量）
    "monthly_labor_cash": {
        "deps": ["employee_count", "avg_salary"],
        "formula": lambda p: (p.get("employee_count") or 0) * (p.get("avg_salary") or 0) or None,
        "label": "月人工", "unit": "元/月", "kind": "derived", "_hidden": True,
        "describe": lambda p: f"员工 {p.get('employee_count', 0):g} 人 × 人均 {p.get('avg_salary', 0):g} 元",
    },
    # 月人工（含负担）：裸薪 × (1+负担率)
    "monthly_labor": {
        "deps": ["monthly_labor_cash", "labor_burden"],
        "formula": lambda p: (p.get("monthly_labor_cash") or 0) * (1 + (p.get("labor_burden") or 0)) or None,
        "label": "月人工", "unit": "元/月", "kind": "derived",
        "describe": lambda p: (f"员工 {p.get('employee_count', 0):g} 人 × 人均 {p.get('avg_salary', 0):g} 元"
                               + (f" ×(1+{p.get('labor_burden_rate', 0):.0%}负担)"
                                  if p.get("labor_burden_rate") else "")),
    },
    # 月固定成本：组件求和（有值组件之和，无值跳过，全 None → None）
    "monthly_fixed_cost": {
        "deps": ["monthly_rent", "monthly_labor"],
        "formula": lambda p: (
            sum(v for v in [
                p.get("monthly_rent"), p.get("monthly_labor"),
                p.get("utilities"), p.get("packaging"),
                p.get("commission"), p.get("other_fixed"),
            ] if v is not None) or None
        ),
        "label": "月固定成本", "unit": "元/月", "kind": "override",
        "describe": lambda p: _describe_fixed_cost(p),
    },
    # 月变动成本：月营收 × 变动成本率
    "monthly_variable_cost": {
        "deps": ["monthly_revenue", "variable_cost_ratio"],
        "formula": lambda p: (p.get("monthly_revenue") or 0) * (p.get("variable_cost_ratio") or 0) or None,
        "label": "月变动成本", "unit": "元/月", "kind": "derived",
        "describe": lambda p: f"月营收 {p.get('monthly_revenue', 0):g} × 变动成本率 {p.get('variable_cost_ratio', 0):.0%}",
    },
    # 月利润：营收 - 固定 - 变动
    "monthly_profit": {
        "deps": ["monthly_revenue", "monthly_fixed_cost", "monthly_variable_cost"],
        "formula": lambda p: (
            (p.get("monthly_revenue") or 0) - (p.get("monthly_fixed_cost") or 0)
            - (p.get("monthly_variable_cost") or 0)
            if all(p.get(d) is not None for d in ("monthly_revenue", "monthly_fixed_cost", "monthly_variable_cost"))
            else None
        ),
        "label": "月利润", "unit": "元/月", "kind": "override", "user_direct_ok": True,
        "describe": lambda p: (f"月营收 {p.get('monthly_revenue', 0):g} − 月固定成本 {p.get('monthly_fixed_cost', 0):g}"
                               f" − 月变动成本 {p.get('monthly_variable_cost', 0):g}"),
    },
    # 单位变动成本：客单价 × 变动成本率
    "variable_cost_per_unit": {
        "deps": ["price_per_unit", "variable_cost_ratio"],
        "formula": lambda p: (p.get("price_per_unit") or 0) * (p.get("variable_cost_ratio") or 0) or None,
        "label": "单位变动成本", "unit": "元/单位", "kind": "derived",
        "describe": lambda p: f"客单价 {p.get('price_per_unit', 0):g} × 变动成本率 {p.get('variable_cost_ratio', 0):.0%}",
    },
    # 年固定成本：月固定 × 12
    "annual_fixed_cost": {
        "deps": ["monthly_fixed_cost"],
        "formula": lambda p: (p.get("monthly_fixed_cost") or 0) * 12 or None,
        "label": "年固定成本", "unit": "元/年", "kind": "derived",
        "describe": lambda p: f"月固定成本 {p.get('monthly_fixed_cost', 0):g} × 12",
    },
    # 毛利率：1 - 变动成本率（S3：统一 0~1 口径，展示时 ×100）
    "gross_margin": {
        "deps": ["variable_cost_ratio"],
        "formula": lambda p: round(1 - p.get("variable_cost_ratio", 0), 4) if p.get("variable_cost_ratio") is not None else None,
        "label": "毛利率", "unit": "0~1", "kind": "derived",
        "display_percent": True,   # 内部 0~1，展示为百分数
        "describe": lambda p: f"1 − 变动成本率 {p.get('variable_cost_ratio', 0):.0%}",
    },
    # 可用现金：总投资（设备占比可选扣减）
    "available_cash": {
        "deps": ["total_investment"],
        "formula": lambda p: (
            p.get("total_investment") * (1 - p.get("equipment_ratio", 0))
            if p.get("equipment_ratio") is not None
            else p.get("total_investment")
        ) if p.get("total_investment") is not None else None,
        "label": "可用现金", "unit": "元", "kind": "derived",
        "describe": lambda p: (
            f"总投资 {p.get('total_investment', 0):g} ×(1−设备占比 {p.get('equipment_ratio', 0):.0%})"
            if p.get("equipment_ratio") is not None
            else f"总投资 {p.get('total_investment', 0):g}"
        ),
    },
}


# ── 字段分类体系 ────────────────────────────────────────────────────────
# A 类（纯输入）：用户直接给，无公式 → INPUT_SPECS 中的字段
# B 类（可覆盖）：用户可直接给，也可公式推 → DERIVED_SPECS 中 kind="override"
# C 类（纯派生）：只能公式推 → DERIVED_SPECS 中 kind="derived"

PURE_INPUT_FIELDS: set = set(INPUT_SPECS.keys())
OVERRIDABLE_FIELDS: set = {name for name, spec in DERIVED_SPECS.items() if spec.get("kind") == "override"}
PURE_DERIVED_FIELDS: set = {name for name, spec in DERIVED_SPECS.items() if spec.get("kind") == "derived"}

# B 类字段依赖关系：当 A 类依赖字段变化时，清掉 B 类用户覆盖
B_FIELD_DEPENDENCIES: dict = {
    "monthly_revenue": ["daily_traffic", "price_per_unit"],
    "variable_cost_ratio": ["unit_variable_cost", "price_per_unit", "gross_margin"],
    "monthly_profit": ["monthly_revenue", "monthly_fixed_cost", "monthly_variable_cost"],
    "gross_margin": ["variable_cost_ratio"],
}


def clear_stale_overrides(old_params: dict, new_params: dict, user_overrides: dict) -> dict:
    """当 A 类依赖字段变化时，清掉旧 B 类用户值。
    
    参数：
        old_params: 历史参数
        new_params: 本轮新参数
        user_overrides: 当前 B 类字段用户覆盖 {field: value}
    
    返回：
        更新后的 user_overrides（已清除失效覆盖）
    """
    for b_field, deps in B_FIELD_DEPENDENCIES.items():
        if b_field not in user_overrides:
            continue
        for dep in deps:
            old_val = old_params.get(dep)
            new_val = new_params.get(dep)
            if old_val != new_val:
                # 依赖变化 → 清掉 B 类用户覆盖
                del user_overrides[b_field]
                break
    return user_overrides


# ── 统一字段注册表 ──────────────────────────────────────────────────────

def field_label(name: str) -> str:
    """字段中文名：先查派生表，再查输入表，兜底字段名。"""
    if name in DERIVED_SPECS:
        return DERIVED_SPECS[name]["label"]
    return INPUT_SPECS.get(name, {}).get("label", name)


# ── 固定成本组件展示 ────────────────────────────────────────────────────

_FIXED_COST_COMPONENTS = [
    ("租金", "monthly_rent"),
    ("人工", "monthly_labor"),
    ("水电", "utilities"),
    ("包装", "packaging"),
    ("提成", "commission"),
    ("其他固定", "other_fixed"),
]


def _describe_fixed_cost(p: Dict[str, Any]) -> str:
    """动态列出实际存在的固定成本组件。"""
    has_labor = p.get("employee_count") is not None and p.get("avg_salary") is not None
    parts: List[str] = []
    for label, key in _FIXED_COST_COMPONENTS:
        if key == "monthly_labor":
            if has_labor:
                parts.append(f"人工 ({p.get('employee_count', 0):g}×{p.get('avg_salary', 0):g})")
            continue
        if p.get(key) is not None:
            parts.append(label)
    return " + ".join(parts) if parts else "固定成本组件"


# ── 通用求值器（拓扑求值 + 循环检测）────────────────────────────────────

def _topo_order() -> List[str]:
    """按依赖拓扑排序派生字段。检测循环依赖。"""
    order: List[str] = []
    in_progress: set = set()
    done: set = set()

    def visit(name: str, path: tuple = ()):
        if name in done:
            return
        if name in in_progress:
            cycle = " → ".join(path + (name,))
            raise ValueError(f"字段模型存在循环依赖: {cycle}")
        in_progress.add(name)
        for dep in DERIVED_SPECS[name]["deps"]:
            if dep in DERIVED_SPECS:
                visit(dep, path + (name,))
        in_progress.discard(name)
        done.add(name)
        order.append(name)

    for name in DERIVED_SPECS:
        visit(name)
    return order


_DERIVED_ORDER = _topo_order()


def derive(params: Dict[str, Any], user_overrides: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Optional[float]], Dict[str, Dict[str, Any]]]:
    """求值所有派生字段。

    返回 (values, meta):
    - values: {field: value 或 None}
    - meta:   {field: {source: "user"|"derived"|"missing", formula: str(带数字)}}
      source="user"  → 用户直接给了该值（来自 user_overrides 或 params）
      source="derived" → 公式精确推出
      source="missing" → 缺依赖，无法算

    核心逻辑：
    - B 类字段（kind="override"）：优先查 user_overrides → 有值用用户值；无值 → 公式
    - C 类字段（kind="derived"）：始终公式推
    - 公式返回 None 即 missing
    """
    work: Dict[str, Any] = dict(params)
    values: Dict[str, Optional[float]] = {}
    meta: Dict[str, Dict[str, Any]] = {}
    user_overrides = user_overrides or {}

    for name in _DERIVED_ORDER:
        spec = DERIVED_SPECS[name]
        # ① B 类字段：优先查 user_overrides
        if spec.get("kind") == "override" and name in user_overrides and user_overrides[name] is not None:
            val = user_overrides[name]
            values[name] = val
            work[name] = val
            formula_desc = "用户直接给出"
            if spec.get("describe"):
                try:
                    formula_desc = spec["describe"](work)
                except (KeyError, TypeError, ValueError):
                    pass
            meta[name] = {"source": "user", "formula": formula_desc}
            continue
        # ② 用户已直接给（override 语义，兼容旧逻辑）→ 用用户值
        if name in params and params.get(name) is not None:
            val = params[name]
            values[name] = val
            work[name] = val
            # 仍然算 describe（带数字公式），「用户直接给出」由 derived_values 靠 src 判定
            formula_desc = "用户直接给出"
            if spec.get("describe"):
                try:
                    formula_desc = spec["describe"](work)
                except (KeyError, TypeError, ValueError):
                    pass
            meta[name] = {"source": "user", "formula": formula_desc}
            continue
        # ③ 尝试公式求值
        try:
            val = spec["formula"](work)
        except (TypeError, KeyError, ZeroDivisionError):
            val = None
        if val is not None:
            work[name] = val
            values[name] = val
            # 公式说明
            formula_desc = "公式推导"
            if spec.get("describe"):
                try:
                    formula_desc = spec["describe"](work)
                except (KeyError, TypeError, ValueError):
                    pass
            meta[name] = {"source": "derived", "formula": formula_desc}
        else:
            values[name] = None
            meta[name] = {"source": "missing", "formula": ""}
    return values, meta


# ── 一致性规则 ──────────────────────────────────────────────────────────

def _rule_revenue_vs_traffic_price(params: Dict[str, Any]) -> Optional[str]:
    rev = params.get("monthly_revenue")
    traffic = params.get("daily_traffic")
    price = params.get("price_per_unit")
    if all(isinstance(x, (int, float)) and x > 0 for x in (rev, traffic, price)):
        implied = traffic * price * 30
        if abs(implied - rev) / rev > 0.5:
            return (f"月营收 {rev:,.0f} 与「日均{traffic:g}×单价{price:g}×30天」"
                    f"推算 {implied:,.0f} 差异超 50%，请确认口径")
    return None


def _rule_cost_structure(params: Dict[str, Any]) -> Optional[str]:
    rev = params.get("monthly_revenue")
    vc_ratio = params.get("variable_cost_ratio")
    fixed = params.get("monthly_fixed_cost")
    if all(isinstance(x, (int, float)) for x in (rev, vc_ratio, fixed)):
        if isinstance(rev, (int, float)) and rev > 0:
            total_cost = fixed + rev * vc_ratio
            if total_cost > rev * 10:
                return (f"总成本 {total_cost:,.0f} 超月营收 {rev:,.0f} 10 倍，"
                        f"参数组合物理上不可持续")
    return None


CONSISTENCY_RULES: List[Callable[[Dict[str, Any]], Optional[str]]] = [
    _rule_revenue_vs_traffic_price,
    _rule_cost_structure,
]


def consistency_issues(params: Dict[str, Any]) -> List[Dict[str, str]]:
    """求值后跑一致性规则，返回 [{field, message}]。"""
    issues: List[Dict[str, str]] = []
    for rule in CONSISTENCY_RULES:
        msg = rule(params)
        if msg:
            issues.append({"field": "consistency", "message": msg})
    return issues


def conflict_resolution_ops(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """当一致性规则检出冲突时，自动生成「口径对齐 ops」让用户一键确认。

    每个 op 是 {propose, label, changes, reason}，走现有「应用X」确认流。
    不靠 LLM 猜——规则层自己给出两个修正方向。
    """
    ops: List[Dict[str, Any]] = []
    rev = params.get("monthly_revenue")
    traffic = params.get("daily_traffic")
    price = params.get("price_per_unit")
    if all(isinstance(x, (int, float)) and x > 0 for x in (rev, traffic, price)):
        implied = traffic * price * 30
        if abs(implied - rev) / rev > 0.5:
            # 方案A：按客流×单价×30 修正月营收
            ops.append({
                "propose": "set", "label": f"月营收改为 {implied:,.0f}（按客流×单价×30）",
                "changes": {"monthly_revenue": implied},
                "reason": f"客流{traffic:g}×单价{price:g}×30天 = {implied:,.0f}",
                "hypothesis": None,
            })
            # 方案B：按月营收反推客流
            implied_traffic = round(rev / (price * 30), 0)
            ops.append({
                "propose": "set", "label": f"客流改为 {implied_traffic:.0f}/天（按月营收反推）",
                "changes": {"daily_traffic": implied_traffic},
                "reason": f"月营收{rev:,.0f} ÷ ({price:g}×30) = {implied_traffic:.0f}",
                "hypothesis": None,
            })
    return ops


# ── missing 根因追溯 ────────────────────────────────────────────────────

def _missing_root_causes(field: str, params: Dict[str, Any],
                          values: Dict[str, Optional[float]],
                          _seen: Optional[set] = None) -> List[str]:
    """追溯某派生字段缺算的根因（到底缺哪些用户输入）。"""
    if _seen is None:
        _seen = set()
    causes: List[str] = []
    spec = DERIVED_SPECS.get(field)
    if not spec:
        return causes
    # override 字段：用户没给、也没推导出 → 它自己就是根因（用户该给这个）
    if spec.get("kind") == "override" and params.get(field) is None and values.get(field) is None:
        causes.append(field_label(field))
    for d in spec["deps"]:
        if d in _seen:
            continue
        _seen.add(d)
        if d in DERIVED_SPECS:
            if values.get(d) is None:
                causes.extend(_missing_root_causes(d, params, values, _seen))
        else:
            if params.get(d) is None:
                causes.append(field_label(d))
    return causes


# ── 精确推算层清单（供 formatter / decision 消费）────────────────────────

def derived_values(params: Dict[str, Any], src: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """生成「精确推算层」清单。

    每个派生字段：{field, label, value, unit, formula(带数字), status(ok/missing),
    missing(缺什么)}。公式与 derive() 同源，不再手写第二份。
    """
    src = src or {}
    out: List[Dict[str, Any]] = []
    values, meta = derive(params)

    for name in _DERIVED_ORDER:
        spec = DERIVED_SPECS[name]
        if spec.get("_hidden"):
            continue
        val = values.get(name)
        m = meta.get(name, {})
        # 展示口径：内部 0~1 的比例类字段（毛利率 / 变动成本率）在展示层 ×100 成百分数。
        # 既保持与旧版一致的视觉，也修掉「0.4 0~1」被 f"{v:,.0f}" 渲染成「0 0~1」的错。
        disp_val, disp_unit = val, spec["unit"]
        if spec.get("display_percent") and isinstance(val, (int, float)):
            disp_val, disp_unit = round(val * 100, 1), "%"
        item: Dict[str, Any] = {
            "field": name, "label": spec["label"], "unit": disp_unit,
            "status": "ok" if val is not None else "missing",
        }
        if val is not None:
            item["value"] = round(disp_val, 2) if isinstance(disp_val, float) else disp_val
            # 公式说明：仅「用户可直接给」且来源确为[用户]时写「用户直接给出」
            s = src.get(name, "")
            if s.startswith("[用户]") and spec.get("user_direct_ok"):
                item["formula"] = "用户直接给出"
            else:
                item["formula"] = m.get("formula", "公式推导")
        else:
            item["value"] = None
            item["formula"] = ""
            causes = _missing_root_causes(name, params, values)
            item["missing"] = "、".join(dict.fromkeys(causes)) if causes else "依赖输入"
        out.append(item)
    return out
