"""ops 执行器 — LLM 编排提议的校验与应用（Tier 1，人在环）

LLM 在解读里输出 ```ops 块提议候选方案 / 单值改动。本模块做三件事：
1. 校验：白名单（基础字段可改，派生字段拒绝）+ param_guard 合理性检查
2. 预览：把每个 op 应用到 session 后跑 quick_scan，得出「方案X→月利润Y」
3. 应用：用户回「应用」/「应用X」才真正写入 SessionState——LLM 不可静默执行

设计原则：
- LLM 只有提议权，没有执行权；执行权在用户的确认词 + 本模块的校验闸门
- 派生字段（monthly_labor / monthly_fixed_cost / monthly_profit / runway 等）一概拒绝
- 校验过 param_guard 的 op 才进预览/应用；其余拒绝并返回原因
"""

import json
import logging
from typing import Any, Dict, List, Tuple, Optional

from param_guard import guard_extracted, validate_field, LEVEL_CRITICAL

logger = logging.getLogger(__name__)


# 基础字段白名单：用户/LLM 可改的原子参数。派生字段一律不在内。
BASE_FIELDS = {
    "industry", "monthly_rent", "monthly_revenue", "total_investment",
    "price_per_unit", "daily_traffic", "employee_count", "avg_salary",
    "variable_cost_ratio", "gross_margin", "monthly_growth_rate",
    "founder_count", "city", "stage", "monthly_expense",
    "utilities", "packaging", "commission", "other_fixed",
    "unit_variable_cost",
}

# 派生字段黑名单：靠引擎重算，绝对不让 ops 触碰。
DERIVED_FIELDS = {
    "monthly_labor", "monthly_labor_cash", "labor_burden_rate",
    "monthly_fixed_cost", "monthly_variable_cost", "monthly_profit",
    "available_cash", "runway_months", "annual_fixed_cost",
    "breakeven_sales", "daily_breakeven", "breakeven_revenue_monthly",
}


def _normalize_op(op: dict) -> dict:
    """规整单个 op，补充缺省键。"""
    propose = op.get("propose", "set")
    out = {"propose": propose}
    for k in ("label", "reason", "field", "value", "changes"):
        if k in op:
            out[k] = op[k]
    if propose == "set" and "field" in op and "value" in op:
        out["changes"] = {op["field"]: op["value"]}
    return out


def validate_op(op: dict) -> Tuple[bool, str]:
    """校验单个 op 是否可执行。

    返回 (ok, reason)。reason 在 reject 时为拒绝原因，ok 时为空串。
    """
    op = _normalize_op(op)
    propose = op.get("propose")
    changes = op.get("changes") or {}

    if propose not in ("set", "try"):
        return False, f"未知 propose 类型 {propose!r}"

    if not changes:
        return False, "op 缺 changes/field+value"

    for k in changes:
        if k in DERIVED_FIELDS:
            return False, f"{k} 是派生字段（靠引擎重算），不可直接改"
        if k not in BASE_FIELDS:
            return False, f"{k} 不在可改白名单内"

        v = changes[k]
        # param_guard 合理性（数值字段硬边界检查）
        check = validate_field(k, v)
        if check["level"] == LEVEL_CRITICAL and check["auto_fix"] is None:
            return False, f"{k}={v} 物理不可能: {check['message']}"

    return True, ""


def preview_op(op: dict, base_params: dict, scanner) -> Optional[dict]:
    """为单个 op 计算预览：应用改动 → 跑引擎 → 取关键指标。

    scanner：quick_scan 工具实例（@tool）。
    base_params：当前会话的 merge 后参数。
    返回 {label, changes, profit_after, fixed_after, revenue_after, ok, reason}。
    """
    op = _normalize_op(op)
    ok, reason = validate_op(op)
    if not ok:
        return {
            "label": op.get("label", op.get("propose", "")),
            "changes": op.get("changes") or {},
            "ok": False, "reason": reason,
        }
    changes = op["changes"]
    # 应用临时改动，含元数据不变
    preview_params = dict(base_params or {})
    for k, v in changes.items():
        preview_params[k] = v
    # 派生字段 / 守门检测过的抽参：交给引擎前同样过 guard_extracted
    cleaned, _ = guard_extracted(preview_params, industry=preview_params.get("industry"))
    params_json = json.dumps(cleaned, ensure_ascii=False)
    try:
        scan = json.loads(scanner.invoke({"params_json": params_json}))
    except Exception as e:
        logger.warning(f"ops 预览 quick_scan 失败: {e}")
        return {
            "label": op.get("label", op.get("propose", "")),
            "changes": changes, "ok": False, "reason": f"引擎计算失败: {e}",
        }
    profit = None
    fixed = None
    revenue = None
    cm = scan.get("core_metrics") or {}
    profit = cm.get("monthly_profit")
    fixed = (scan.get("params") or {}).get("monthly_fixed_cost")
    revenue = cm.get("monthly_revenue")
    return {
        "label": op.get("label", changes and "、".join(f"{k}={v}" for k, v in changes.items()) or op.get("propose", "")),
        "changes": changes,
        "ok": True, "reason": "",
        "profit_after": profit, "fixed_after": fixed, "revenue_after": revenue,
    }


def apply_op(op: dict, thread_id: str, session_apply_fn,
             hypothesis: Optional[str] = None) -> Tuple[bool, str, dict]:
    """真正写入 SessionState 并重算引擎（用户确认后才调）。

    session_apply_fn(thread_id, params) -> state：把 changes 写进 session 的函数
        （由 web_server 传 apply_turn 或 apply_turn_guarded）。
    hypothesis：若该 op 来自行业/LLM 候选假设（如 "行业模板(餐饮)"），
        则额外登记 _accepted_hypotheses，供决策层区分「用户事实 vs 假设」（P0）。
    返回 (ok, reason, merged_params)。
    """
    op = _normalize_op(op)
    ok, reason = validate_op(op)
    if not ok:
        return False, reason, {}
    changes = op["changes"]
    # 送进 session_state：清理过的值（去掉内部 _guard 这种键）
    cleaned, _ = guard_extracted(changes)
    try:
        state = session_apply_fn(thread_id, cleaned)
        merged = dict(state.get("params") or {})
        if hypothesis:
            for fld in cleaned:
                record = _find_hypothesis_recorder()
                if record is not None:
                    record(thread_id, fld, cleaned[fld], hypothesis)
    except Exception as e:
        return False, f"会话写入失败: {e}", {}
    return True, "", merged


def _find_hypothesis_recorder():
    """惰性引用 session_state.record_accepted_hypothesis，避免顶层 import 环。"""
    try:
        from session_state import record_accepted_hypothesis
        return record_accepted_hypothesis
    except Exception:
        return None


def parse_apply_command(text: str) -> Optional[int]:
    """从用户输入识别「应用」/「应用A」/「应用方案A」/「应用1」命令。

    返回 None 表示非应用命令；0 表示「应用」（默认第一个）；n>=1 表示指定第 n 个。
    """
    if not text:
        return None
    t = text.strip()
    if not t:
        return None
    # 简化匹配：必须以"应用"开头
    if not t.startswith("应用"):
        return None
    rest = t[2:].strip()
    if not rest:
        return 0  # 「应用」→ 取第一个候选
    # 「应用A」「应用方案A」「应用1」「应用第1个」
    for tag, idx in (("A", 1), ("B", 2), ("C", 3), ("D", 4), ("方案A", 1), ("方案B", 2),
                      ("方案C", 3), ("方案D", 4)):
        if rest.startswith(tag):
            return idx
    # 纯数字
    if rest[0].isdigit():
        try:
            n = int(rest[0])
            return n
        except ValueError:
            return None
    return 0  # 兜底：「应用...」模糊命中，取第一个


OP_CONFIRMATION_PREFIX = "🛠 **候选方案（回复「应用X」生效，LLM 不直接改）**"