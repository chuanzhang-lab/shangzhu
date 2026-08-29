"""Phase 0 验收测试：置信层 + 门禁 + 默认人力策略（决策A①③ / 决策B）。

运行：uv run pytest tests/test_quick_scan_phase0.py
（pyproject 已设 pythonpath=src，可直接 import tools / router）
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tools.workflow_engine import quick_scan, compare_scenarios, trend_projection
from router.formatter import format_response


def _scan(json_str):
    return json.loads(quick_scan.invoke({"params_json": json_str}))


def test_only_rent_is_blocked_by_gate():
    """仅给租金 8000 → 被门禁拦下，返回骨架，不再误报 月亏2万/危险。"""
    d = _scan('{"monthly_rent": 8000}')
    assert d.get("insufficient") is True
    assert any("月营收" in g for g in d["gaps"])
    assert d["param_sources"]["available_cash"].startswith("[缺失]")
    assert d["param_sources"]["employee_count"].startswith("[缺失]")
    md = format_response("quick_scan", d)
    assert "危险" not in md
    assert "月亏" not in md


def test_rent_plus_revenue_missing_vc_is_blocked():
    """租金+营收 但未给变动成本率 → 利润/保本「还不能定」：月利润为 None + 缺口号，不产假硬数。"""
    d = _scan('{"monthly_rent": 8000, "monthly_revenue": 50000}')
    assert d.get("insufficient") is not True  # 基础参数够，仍渲染（不全盘退回骨架）
    assert d["core_metrics"]["monthly_profit"] is None
    assert d["param_sources"]["variable_cost_ratio"].startswith("[缺失]")
    # 缺口信息应出现在假设清单/来源标注（替代旧 skeleton.gaps）
    kinds = {a["field"]: a["kind"] for a in d["assumptions"]}
    assert kinds.get("variable_cost_ratio") == "缺失"
    md = format_response("quick_scan", d)
    assert "月亏" not in md
    assert "还不能定" in md or "变动成本率" in md  # 明确提示补 vc，而非假硬数


def test_rent_plus_revenue_shows_profit_not_false_alarm():
    """租金+营收+变动成本率 → 出利润，人工按0标缺失，跑道未知（不误报）。"""
    d = _scan('{"monthly_rent": 8000, "monthly_revenue": 50000, "variable_cost_ratio": 0.4}')
    assert d.get("insufficient") is not True
    assert d["core_metrics"]["monthly_profit"] == 22000
    assert d["params"]["monthly_fixed_cost"] == 8000          # 人工按 0，不再虚构 12000
    assert d["params"]["available_cash"] is None               # 总投资缺失→不污染跑道
    assert d["status"]["cash"] == "⚪ 未知（需总投资）"
    assert d["param_sources"]["employee_count"].startswith("[缺失]")
    fields = [a["field"] for a in d["assumptions"]]
    assert "employee_count" in fields and "total_investment" in fields


def test_full_case_no_regression():
    """完整餐饮案例 → 正常计算，无崩溃，人工为用户值，跑道非未知。"""
    d = _scan('{"industry":"餐饮","monthly_rent":15000,"employee_count":3,'
              '"avg_salary":7000,"variable_cost_ratio":0.55,'
              '"daily_traffic":50,"price_per_unit":25,"total_investment":300000}')
    assert d.get("insufficient") is not True
    assert d["params"]["available_cash"] is not None
    assert d["param_sources"]["employee_count"].startswith("[用户]")
    assert "error" not in d
    assert d["core_metrics"]["runway_months"] != "未知"


# ─── compare_scenarios 防崩溃回归（2026-08-17）────────────────────────────

def _cmp(base_json, alt_json):
    return json.loads(compare_scenarios.invoke({"base_json": base_json, "alt_json": alt_json}))


def test_compare_missing_vc_degrades_not_crashes():
    """缺变动成本率时 compare 应降级返回缺口提示，而不是 None-None 崩溃。

    复现路径：用户给 月租/客流/客单 但没给变动成本率 → insufficient 只拦月营收
    （vc 缺失是软缺口，insufficient=False），但 monthly_profit=None →
    旧代码 diff 减法直接 TypeError；修复后应返回 insufficient=True + 明确提示。
    """
    base = '{"monthly_rent":15000,"daily_traffic":50,"price_per_unit":25,"employee_count":3,"avg_salary":5000}'
    alt = '{"monthly_rent":8000,"daily_traffic":50,"price_per_unit":25,"employee_count":3,"avg_salary":5000}'
    d = _cmp(base, alt)
    assert d.get("insufficient") is True
    assert "变动成本率" in d.get("message", "")
    assert any("方案A" in g and "月利润" in g for g in d.get("gaps", []))
    assert "error" not in d  # 不裸崩


def test_compare_full_params_succeeds():
    """补全变动成本率后 compare 正常出对比表（回归护栏）。"""
    base = '{"monthly_rent":15000,"daily_traffic":50,"price_per_unit":25,"employee_count":3,"avg_salary":5000,"variable_cost_ratio":0.4}'
    alt = '{"monthly_rent":8000,"daily_traffic":50,"price_per_unit":25,"employee_count":3,"avg_salary":5000,"variable_cost_ratio":0.4}'
    d = _cmp(base, alt)
    assert d.get("insufficient") is not True
    assert "diff" in d and "profit" in d["diff"]
    assert d["base_scenario"]["monthly_profit"] is not None
    assert "error" not in d


# ─── trend 统一降级（M1，2026-08-19）──────────────────────────────────────

def _trend(pj):
    return json.loads(trend_projection.invoke({"params_json": pj}))


def test_trend_missing_vc_degrades_not_crashes():
    """缺变动成本率时 trend 应返回统一降级提示，而不是 error JSON。

    旧行为：vc 缺失是软缺口（insufficient=False），直接进入 _project_trend_12m，
    `revenue * vc_ratio` 因 vc=None 抛 TypeError → 被 try/except 兜成 {"error":...}。
    修复后：走 _profit_readiness 统一降级，返回 insufficient=True + 明确「缺变动成本率」。
    """
    pj = '{"monthly_revenue":20000,"daily_traffic":50,"price_per_unit":25}'
    d = _trend(pj)
    assert d.get("insufficient") is True
    assert d.get("tool") == "trend"
    assert "变动成本率" in d.get("message", "")
    assert "error" not in d


def test_trend_full_params_succeeds():
    """补全变动成本率与固定成本后 trend 正常输出 12 个月趋势（回归护栏）。"""
    pj = ('{"monthly_rent":15000,"daily_traffic":50,"price_per_unit":25,'
          '"employee_count":3,"avg_salary":5000,"variable_cost_ratio":0.4}')
    d = _trend(pj)
    assert d.get("insufficient") is not True
    assert "months" in d and len(d["months"]) == 12
    assert "summary" in d
    assert "error" not in d


# ─── 独立运行入口（无需 pytest）──────────────────────────────────────────

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
        except Exception as e:  # noqa
            print(f"ERROR {t.__name__}: {e}")
            failed += 1
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)
