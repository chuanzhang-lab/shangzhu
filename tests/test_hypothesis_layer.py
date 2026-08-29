"""Phase 0 · 数据基础层验收：取消「输入伪造型默认」 + basis 分类 + 假设确认流。

覆盖：
- H1 缺薪资 → 不再出现「人工19,600 [推算]」假硬数（G1）
- H2 缺变动成本率 → 利润/保本「还不能定」+ 缺口标注（G6）
- H3 用户给齐 → 全 [用户] basis=user，无行业默认（G2）
- H4 benchmark 永不进入利润公式（G3）
- H5 basis 分类暴露（user/missing/hypothesis）
- H6 已采纳假设经「应用X」登记 _accepted_hypotheses（P0-4/P0-5）
- H7 行业模板值仅作为候选（hypotheses 区），不自动填进计算图（D2/D4）

运行：并入 tests/run_all.py；也可 .venv/bin/python tests/test_hypothesis_layer.py
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tools.workflow_engine import quick_scan, _get_industry_templates, _get_hypothesis_fields
from router.formatter import format_response
from session_state import (
    apply_turn, reset_state, record_accepted_hypothesis, get_accepted_hypotheses,
)


def _scan(params_dict: dict) -> dict:
    return json.loads(quick_scan.invoke(
        {"params_json": json.dumps(params_dict, ensure_ascii=False)}))


def test_h1_missing_salary_no_fake_labor():
    """G1：用户给人数不给薪资 → 不再出现 行业默认 7000 撑起的假人工。"""
    d = _scan({"industry": "餐饮", "total_investment": 200000, "price_per_unit": 10,
               "daily_traffic": 60, "monthly_rent": 1800, "employee_count": 2})
    assert d.get("error") is None
    assert d["param_sources"]["avg_salary"].startswith("[缺失]"), d["param_sources"]["avg_salary"]
    assert d["params"].get("monthly_labor") is None, "不得用默认薪资撑起人工"
    md = format_response("quick_scan", d)
    assert "19,600" not in md
    assert "19600" not in md


def test_h2_missing_vc_not_conclusion():
    """G6：缺变动成本率 → 利润「还不能定」，非假硬数。"""
    d = _scan({"monthly_rent": 8000, "monthly_revenue": 50000})
    assert d.get("error") is None
    assert d["core_metrics"]["monthly_profit"] is None
    assert d["param_sources"]["variable_cost_ratio"].startswith("[缺失]")
    kinds = {a["field"]: a["kind"] for a in d["assumptions"]}
    assert kinds.get("variable_cost_ratio") == "缺失"
    md = format_response("quick_scan", d)
    assert "还不能定" in md or "变动成本率" in md


def test_h3_all_user_facts():
    """G2：全给齐 → 全部用户事实，basis=user，无行业默认。"""
    d = _scan({"industry": "餐饮", "total_investment": 200000, "price_per_unit": 10,
               "daily_traffic": 60, "monthly_rent": 1800,
               "employee_count": 2, "avg_salary": 3000, "variable_cost_ratio": 0.55})
    assert d["param_sources"]["avg_salary"].startswith("[用户]")
    assert d["param_sources"]["variable_cost_ratio"].startswith("[用户]")
    assert d["basis"]["avg_salary"] == "user"
    assert d["basis"]["variable_cost_ratio"] == "user"
    assert d["core_metrics"]["monthly_profit"] is not None
    assert d["params"]["monthly_labor"] == 6000.0  # 2×3000（无默认社保负担）


def test_h4_benchmark_not_in_formula():
    """G3：benchmark 仅对比标尺，不参与利润/跑道公式。"""
    d = _scan({"industry": "餐饮", "total_investment": 200000, "price_per_unit": 10,
               "daily_traffic": 60, "monthly_rent": 1800,
               "employee_count": 2, "avg_salary": 3000, "variable_cost_ratio": 0.55})
    # 利润应严格 = 营收-固定-变动，与 benchmark 数值区间无关
    rev = d["core_metrics"]["monthly_revenue"]
    mfc = d["params"]["monthly_fixed_cost"]
    vc = rev * 0.55
    assert d["core_metrics"]["monthly_profit"] == round(rev - mfc - vc, 0)
    # benchmark 只在独立字段出现，不写进 params 计算链
    assert isinstance(d.get("benchmark"), dict) or d.get("benchmark") is None


def test_h5_basis_classification():
    """P0-1：basis 分类暴露。"""
    d = _scan({"monthly_rent": 5000, "price_per_unit": 20, "daily_traffic": 30})
    b = d.get("basis") or {}
    assert b.get("monthly_rent") == "user", b
    assert b.get("price_per_unit") == "user", b
    assert b.get("variable_cost_ratio") == "missing", b
    assert b.get("avg_salary") == "missing", b


def test_h6_hypothesis_application_records_basis():
    """P0-4/P0-5：用户「应用X」采纳行业候选 → 登记 _accepted_hypotheses。"""
    reset_state("h6")
    apply_turn("h6", {"industry": "餐饮", "avg_salary": None}, "", "餐饮")
    # 模拟用户对行业候选假设「应用A」
    record_accepted_hypothesis("h6", "avg_salary", 7000, "餐饮")
    acc = get_accepted_hypotheses("h6")
    assert acc.get("avg_salary") == {"value": 7000, "industry": "餐饮"}, acc
    # 引擎视角：该字段此时来源仍是用户录入（apply_op 走 apply_turn 后是用户给的）
    # 记录仅用于决策层区分「假设采纳」，不污染 params 来源


def test_h7_industry_candidate_not_auto_filled():
    """D2/D4：行业模板值只在 hypotheses 区，不再自动填进计算图。"""
    tpl = _get_industry_templates().get("餐饮", {})
    assert "hypotheses" in tpl, "餐饮模板应有 hypotheses 区"
    assert "benchmark" in tpl, "餐饮模板应有 benchmark 区"
    assert "avg_salary" in tpl["hypotheses"], "餐饮候选含平均薪资"
    # 输入给行业但不给薪资 → 引擎不用 7000 填充（H1 已证）
    d = _scan({"industry": "餐饮", "monthly_revenue": 20000})
    assert d["param_sources"]["avg_salary"].startswith("[缺失]"), d["param_sources"]["avg_salary"]
    # 假设候选字段清单存在于配置
    hf = _get_hypothesis_fields()
    assert "avg_salary" in hf and "variable_cost_ratio" in hf and "employee_count" in hf


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
