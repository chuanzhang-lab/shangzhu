"""运行链路成熟度 oracle（界面口语句 → 抽取 → 引擎 → 不得静默算错）。

来源：2026-09-14 improve-prompt 五维审查。门禁 428 全绿时，旗舰口语句仍会：
  - 把「工资一共」当人均（人工×2）
  - 漏抽「食材大概35%」
  - 把年租金当月租
  - 无标点连写把客单价串成几十万
  - 缺变动成本率却报跑道「无限」/正向现金流
  - 「还是/如果」误入 compare 不入 session
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from router.param_extractor import extract_params
from router.intent import detect_intent
from tools.workflow_engine import quick_scan, _fill_params
from router.formatter import format_response

TOL = 1e-6
FLAGSHIP = (
    "开家牛肉面店，投资20万，月租8000，两个人工资一共1万2，"
    "一天大概80碗，一碗18块，食材大概35%"
)
NOPUNCT = (
    "开咖啡店投资30万租金8000两个人工资一共1万2"
    "一天大概80单一杯25食材成本大概35%"
)


def _p(text):
    return {k: v for k, v in extract_params(text).items() if not k.startswith("_")}


def _scan(text):
    return json.loads(quick_scan.invoke(
        {"params_json": json.dumps(_p(text), ensure_ascii=False)}))


# ── S2 抽取 ──────────────────────────────────────────────────────────────

def test_mat_flagship_labor_is_total_not_per_person():
    """「两个人工资一共1万2」是总额，人均 6000，不得抽成人均 12000。"""
    p = _p(FLAGSHIP)
    assert p.get("employee_count") == 2.0, p
    assert p.get("avg_salary") == 6000.0, p


def test_mat_flagship_food_cost_ratio():
    """「食材大概35%」必须抽成变动成本率 0.35。"""
    p = _p(FLAGSHIP)
    assert p.get("variable_cost_ratio") is not None, p
    assert abs(p["variable_cost_ratio"] - 0.35) < TOL, p


def test_mat_food_cost_variants():
    for text, exp in {
        "食材大概35%": 0.35,
        "食材成本35%": 0.35,
        "食材成本占40%": 0.40,
        "原料成本35%": 0.35,
    }.items():
        p = _p(text)
        got = p.get("variable_cost_ratio")
        assert got is not None and abs(got - exp) < TOL, f"{text!r} -> {p}"


def test_mat_annual_rent_converted_to_monthly():
    p = _p("房租一年10万")
    assert p.get("monthly_rent") is not None, p
    assert abs(p["monthly_rent"] - 100000 / 12) < 1, p
    p2 = _p("年租金12万")
    assert abs(p2.get("monthly_rent", 0) - 10000) < TOL, p2


def test_mat_deposit_months_not_rent():
    """「押金3个月房租」不得把月租抽成 3。"""
    p = _p("押金3个月房租")
    assert p.get("monthly_rent") != 3.0, p


def test_mat_commission_percent_not_yuan():
    p = _p("美团抽成20%")
    assert p.get("commission") != 20.0, p


def test_mat_nopunct_no_field_collision():
    """无标点连写不得把投资/租金/客流/客单价串台。"""
    p = _p(NOPUNCT)
    assert p.get("total_investment") == 300000.0, p
    assert p.get("monthly_rent") == 8000.0, p
    assert p.get("daily_traffic") == 80.0, p
    assert p.get("price_per_unit") == 25.0, p
    assert p.get("price_per_unit", 0) < 1000, p
    assert abs((p.get("variable_cost_ratio") or 0) - 0.35) < TOL, p
    assert p.get("employee_count") == 2.0, p
    assert p.get("avg_salary") == 6000.0, p


def test_mat_flagship_labor_fill():
    filled, src, _ = _fill_params(extract_params(FLAGSHIP))
    assert filled.get("monthly_labor") == 12000.0, filled.get("monthly_labor")
    assert filled.get("variable_cost_ratio") is not None
    assert filled.get("monthly_profit") is not None


# ── S3 意图 ──────────────────────────────────────────────────────────────

def test_mat_haishi_not_compare():
    intent, _ = detect_intent("我还是开个面馆吧，投资20万月租8000")
    assert intent == "quick_scan", intent


def test_mat_ruguo_first_message_not_compare():
    intent, _ = detect_intent("如果租金是8000，客流100，客单价18")
    assert intent == "quick_scan", intent


def test_mat_ruguo_with_base_stays_compare():
    intent, _ = detect_intent("如果租金是8000", has_base=True)
    assert intent == "compare", intent


def test_mat_strong_compare_kept():
    intent, _ = detect_intent("减租好还是提价好")
    assert intent == "compare", intent


def test_mat_deposit_not_trend():
    intent, _ = detect_intent("押金3个月房租")
    assert intent != "trend", intent


# ── S4 引擎：缺失不当 0 ──────────────────────────────────────────────────

def test_mat_missing_vcr_runway_not_infinite():
    """变动成本率缺失时，不得报跑道无限 / 正向现金流。"""
    p = {
        "industry": "餐饮",
        "monthly_rent": 8000,
        "total_investment": 200000,
        "employee_count": 2,
        "avg_salary": 6000,
        "daily_traffic": 80,
        "price_per_unit": 18,
    }
    d = json.loads(quick_scan.invoke({"params_json": json.dumps(p, ensure_ascii=False)}))
    rw = (d.get("runway") or {}).get("runway_months")
    assert rw != "无限", d.get("runway")
    cash = (d.get("core_metrics") or {}).get("cash_status") or (d.get("status") or {}).get("cash")
    text = format_response("quick_scan", d)
    assert "无限" not in text, text[:800]
    assert "正向现金流" not in text, text[:800]
    assert cash is None or "未知" in str(cash) or "变动成本" in str(cash), cash


def test_mat_flagship_end_to_end_profit_computable():
    d = _scan(FLAGSHIP)
    assert "core_metrics" in d, d
    profit = (d.get("params") or {}).get("monthly_profit")
    if profit is None:
        profit = (d.get("core_metrics") or {}).get("monthly_profit")
    assert profit is not None, d.get("core_metrics")
    # 营收 80×18×30=43200；固定 8000+12000=20000；变动 43200×0.35=15120
    # 利润 = 43200-20000-15120 = 8080
    assert abs(float(profit) - 8080) < 1, profit


# ── S5 守门：餐饮客单价串台剔除 ──────────────────────────────────────────

def test_mat_absurd_price_stripped_for_catering():
    raw = extract_params("开家面馆客单价300000元")
    assert raw.get("price_per_unit") in (None, 0) or raw.get("price_per_unit", 0) < 1000, raw
    g = extract_params("开家面馆客单价300000元").get("_guard") or {}
    # 若抽取到荒谬值，必须 critical + 剔除
    if "price_per_unit" in {k for k in extract_params("开家面馆客单价300000元")}:
        assert False, "荒谬客单价不得进入 cleaned"
