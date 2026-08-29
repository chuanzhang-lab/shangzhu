"""Phase 1 验收测试：灵活度层（③④⑤⑥）。

覆盖：④ 共享校验态（trend/compare 不再静默误报）、③ 情景/区间引擎、
⑤ 叙事>判决、⑥ 模板不确定性驱动区间。

运行方式（无需 pytest）：
    .venv/bin/python3 tests/test_phase1_flexibility.py
若已装 pytest（uv run pytest），也会被自动收集。
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tools.workflow_engine import quick_scan, trend_projection, compare_scenarios
from router.formatter import format_response


def _scan(d: dict):
    return json.loads(quick_scan.invoke({"params_json": json.dumps(d)}))


def _trend(d: dict):
    return json.loads(trend_projection.invoke({"params_json": json.dumps(d)}))


def _compare(base: dict, alt: dict):
    return json.loads(compare_scenarios.invoke({
        "base_json": json.dumps(base), "alt_json": json.dumps(alt)}))


# ─── 测试用例 ─────────────────────────────────────────────────────────────

def test_rent_only_still_blocked():
    """Phase 0 回归：仅租金仍被门禁拦下。"""
    d = _scan({"monthly_rent": 8000})
    assert d.get("insufficient") is True
    assert "危险" not in json.dumps(d)


def test_rent_plus_revenue_shows_scenarios_and_narrative():
    """租金+营收+变动成本率：出仪表盘；利润唯一驱动 vc 已给 → 区间或无差（不假扰动），
    但人工/总投资缺口仍使 has_uncertainty=True。"""
    d = _scan({"monthly_rent": 8000, "monthly_revenue": 50000, "variable_cost_ratio": 0.4})
    assert d.get("insufficient") is not True
    assert d["core_metrics"]["monthly_profit"] == 22000
    sc = d["scenarios"]
    assert sc["has_uncertainty"] is True
    assert any("人工成本" in x for x in sc["drivers"])
    assert any("总投资" in x for x in sc["drivers"])
    # 无默认：利润驱动 vc 为用户给 → 不假扰动区间（best==worst 合理，不等于崩溃）
    assert sc["monthly_profit"]["base"] == 22000
    assert sc["runway"]["base"] is None  # 现金缺失→跑道未知
    assert "人工成本" in d["narrative"]


def test_industry_template_with_vc_uncertainty():
    """行业（餐饮）+ 用户给变动成本率 + 人工缺失 → 情景区间仍产生不确定性。"""
    d = _scan({"industry": "餐饮", "total_investment": 300000, "monthly_rent": 10000,
               "daily_traffic": 100, "price_per_unit": 25,
               "variable_cost_ratio": 0.4})
    assert d.get("insufficient") is not True, d.get("gaps")
    sc = d["scenarios"]
    assert sc["has_uncertainty"] is True
    assert any("人工成本" in x for x in sc["drivers"])
    assert d["narrative"]


def test_trend_no_silent_misreport():
    """④：仅租金时 trend 走骨架，不再输出 12 个月全 -8000 的静默误报。"""
    t = _trend({"monthly_rent": 8000})
    assert t.get("insufficient") is True
    assert "months" not in t


def test_compare_requires_revenue():
    """④：对比基准缺月营收时返回骨架，说明哪一侧不足。"""
    c = _compare({"monthly_rent": 8000},
                 {"monthly_rent": 8000, "monthly_revenue": 50000})
    assert c.get("insufficient") is True
    assert any("方案A" in g for g in c["gaps"])


def test_full_user_input_high_confidence():
    """全部用户显式提供→无不确定性，叙事声明高置信。"""
    d = _scan({"industry": "餐饮", "total_investment": 300000, "monthly_rent": 10000,
               "daily_traffic": 100, "price_per_unit": 25,
               "employee_count": 3, "avg_salary": 7000,
               "variable_cost_rate": 0.4, "monthly_revenue": 75000})
    assert d["scenarios"]["has_uncertainty"] is False
    assert "置信度高" in d["narrative"]


def test_narrative_focuses_material_lever():
    """叙事不应把 stage 等次要默认当成风险焦点。"""
    d = _scan({"industry": "餐饮", "total_investment": 300000, "monthly_rent": 10000,
               "daily_traffic": 100, "price_per_unit": 25,
               "employee_count": 3, "avg_salary": 7000,
               "variable_cost_ratio": 0.4, "monthly_revenue": 75000})
    assert "stage" not in d["narrative"]


# ─── 独立运行入口 ─────────────────────────────────────────────────────────

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
