"""抽取器措辞矩阵 oracle + gross_margin 单位契约双向断言。

背景：2026-09-12 六维审查（PLAN_EXTRACTOR_PIPELINE_FIX_2026-09-12.md）实证出
**4 类常见措辞漏抽/算错** + **gross_margin 单位三处两种口径**。这 5 个缺口在
既有 355 个用例里全都能溜过去（见下）。

本文件把「措辞 → 期望值」固化成矩阵门禁，分四段：
  E1 占比语义的**对象词可省略**（食材成本占40%）
  E2 中文分数「X成」的**语义绑定**（食材成本占4成 / 毛利率六成）
  E3 量词别名（每碗/每杯/每份…+元）
  E4 金额缩写「A万B / A千B」（1万5 → 15000）
  E5 单位成本同义词（食材成本每份8元）
  C  单位契约双向断言（gross_margin 与 variable_cost_ratio 同为 0~1）
  E2E 端到端数字正确性（月利润）

历史缺口（本文件新增前均无覆盖）：
  月租金1万5 → 抽成 10000（丢尾数，_find_number 步骤 1 匹配「1万」即返回）
  食材成本占4成 → 抽成 0.04（差 10 倍，「成」被当阿拉伯数字兜底吞掉）
  每碗18元 → 完全抽不到（price_per_unit 只硬编码了「一杯」）
  食材成本占40% → 完全抽不到（_extract_cost_ratio 要求显式对象词）
  derive({"gross_margin": 0.6}) → vcr 0.994（应为 0.4）

运行：并入 tests/run_all.py（t33）；也可 .venv/bin/python3 tests/test_extractor_coverage.py
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from router.param_extractor import extract_params
from field_model import derive
from tools.workflow_engine import quick_scan

TOL = 1e-6


def _p(text):
    """抽取参数（剥掉 _guard 等内部键）。"""
    return {k: v for k, v in extract_params(text).items() if not k.startswith("_")}


def _scan(text):
    """端到端：文本 → 抽取 → quick_scan 仪表盘。"""
    return json.loads(quick_scan.invoke(
        {"params_json": json.dumps(_p(text), ensure_ascii=False)}))


def _cm(text):
    """取 core_metrics；参数不足时 quick_scan 会返回错误结构，此处显式报出。"""
    d = _scan(text)
    assert "core_metrics" in d, f"quick_scan 未返回 core_metrics（参数不足?）: {d}"
    return d["core_metrics"]


# ── E1：占比语义的对象词可省略 ────────────────────────────────────────────

def test_cov_e1_cost_share_object_word_optional():
    """「食材成本占40%」——对象词（营业额/营收）省略是最自然的说法，不得漏抽。"""
    for text, exp in {
        "食材成本占40%": 0.4,
        "成本占45%": 0.45,
        "原料成本占营业额50%": 0.5,
        "变动成本占营收60%": 0.6,
        "材料成本占收入35%": 0.35,
    }.items():
        p = _p(text)
        got = p.get("variable_cost_ratio")
        assert got is not None and abs(got - exp) < TOL, f"{text!r} -> {p}"


def test_cov_e1_negative_fixed_cost_share():
    """负向：「固定成本/总成本占 X%」是**固定成本占比**，不是变动成本率。"""
    for text in ("月固定成本占40%", "总成本占45%", "固定成本占营收的40%"):
        p = _p(text)
        assert p.get("variable_cost_ratio") is None, f"{text!r} 不该抽成变动成本率 -> {p}"


# ── E2：中文分数「X成」必须绑定成本/毛利语义 ─────────────────────────────

def test_cov_e2_cn_fraction_cost_ratio():
    for text, exp in {
        "食材成本占4成": 0.4,
        "变动成本四成": 0.4,
        "原料成本占营业额五成": 0.5,
        "食材成本占三成": 0.3,
    }.items():
        p = _p(text)
        got = p.get("variable_cost_ratio")
        assert got is not None and abs(got - exp) < TOL, f"{text!r} -> {p}"


def test_cov_e2_cn_fraction_gross_margin():
    for text, exp in {
        "毛利率六成": 0.6,
        "六成毛利": 0.6,
        "毛利率八成": 0.8,
    }.items():
        p = _p(text)
        got = p.get("gross_margin")
        assert got is not None and abs(got - exp) < TOL, f"{text!r} -> {p}"


def test_cov_e2_negative_cheng_other_words():
    """负向：「完成/成员/成为」里的「成」不是分数，绝不能被兜底当数字吞掉。"""
    for text in ("项目完成了", "他是团队的核心成员", "生意成为镇上最好的"):
        p = _p(text)
        assert p.get("variable_cost_ratio") is None, f"{text!r} -> {p}"
        assert p.get("gross_margin") is None, f"{text!r} -> {p}"


# ── E3：量词别名（独立正则，不进场 keyword 列表）──────────────────────────

def test_cov_e3_quantifier_alias_price():
    """餐饮/零售日常量词 + 元/块 → 客单价。"""
    for text, exp in {
        "每碗18元": 18, "每杯15元": 15, "每份12元": 12,
        "每位30元": 30, "每件99元": 99, "每瓶5元": 5, "每个20块": 20,
    }.items():
        p = _p(text)
        assert p.get("price_per_unit") == float(exp), f"{text!r} -> {p}"


def test_cov_e3_negative_unit_cost_not_price():
    """负向（抢词护栏）：「每份成本7元」是**单位变动成本**，绝不能被当售价。"""
    p = _p("每份成本7元")
    assert p.get("price_per_unit") is None, p
    assert p.get("unit_variable_cost") == 7.0, p


def test_cov_e3_no_regression_on_daily_traffic():
    """「每天卖80杯」是客流，不是客单价（每+量词的语法不能误伤「每天」）。"""
    p = _p("每天卖80杯")
    assert p.get("daily_traffic") == 80.0, p
    assert p.get("price_per_unit") is None, p


# ── E4：金额缩写「A万B / A千B」────────────────────────────────────────────

def test_cov_e4_wan_qian_shorthand():
    assert _p("月租金1万5").get("monthly_rent") == 15000.0, _p("月租金1万5")
    assert _p("月租1千5").get("monthly_rent") == 1500.0, _p("月租1千5")
    assert _p("总投资20万8").get("total_investment") == 208000.0, _p("总投资20万8")
    assert _p("月营收3万2").get("monthly_revenue") == 32000.0, _p("月营收3万2")


def test_cov_e4_shorthand_in_compound_sentence():
    """无分隔符连写时仍各归其位。"""
    p = _p("月租1万5客单价20日均卖200碗")
    assert p.get("monthly_rent") == 15000.0, p
    assert p.get("price_per_unit") == 20.0, p
    assert p.get("daily_traffic") == 200.0, p


def test_cov_e4_does_not_eat_following_count():
    """缩写尾数字不得吞掉后面的「N人」。"""
    p = _p("月租2万员工5人")
    assert p.get("monthly_rent") == 20000.0, p
    assert p.get("employee_count") == 5.0, p


# ── E5：单位变动成本同义词（必须带元/块，绝不吞百分比）─────────────────────

def test_cov_e5_unit_cost_synonyms():
    for text, exp in {
        "食材成本每份8元": 8, "每碗成本5元": 5,
        "单位成本7元": 7, "单份原料成本6元": 6,
    }.items():
        p = _p(text)
        assert p.get("unit_variable_cost") == float(exp), f"{text!r} -> {p}"


def test_cov_e5_negative_cost_share_not_unit_cost():
    """负向：「食材成本占营业额45%」是**占比**，不是「每份 45 元」。"""
    p = _p("食材成本占营业额45%，客单价25元")
    assert p.get("variable_cost_ratio") == 0.45, p
    assert "unit_variable_cost" not in p, p


# ── C：gross_margin 单位契约（统一 0~1）双向断言 ──────────────────────────

def test_cov_contract_vcr_from_gm():
    """毛利率 → 变动成本率：同为 0~1 口径。"""
    for gm, exp_vcr in {0.6: 0.4, 0.4: 0.6, 0.75: 0.25}.items():
        d, _ = derive({"gross_margin": gm})
        assert abs(d["variable_cost_ratio"] - exp_vcr) < TOL, (gm, d)


def test_cov_contract_gm_from_vcr():
    """变动成本率 → 毛利率：同为 0~1 口径（0.4 → 0.6，不是 60.0）。"""
    for vcr, exp_gm in {0.4: 0.6, 0.55: 0.45, 0.25: 0.75}.items():
        d, _ = derive({"variable_cost_ratio": vcr})
        assert abs(d["gross_margin"] - exp_gm) < 1e-3, (vcr, d)


def test_cov_contract_roundtrip_identity():
    """双向闭合：gm → vcr → gm 回到原值。"""
    d1, _ = derive({"gross_margin": 0.6})
    d2, _ = derive({"variable_cost_ratio": d1["variable_cost_ratio"]})
    assert abs(d2["gross_margin"] - 0.6) < 1e-3, (d1, d2)


# ── E2E：端到端数字正确性 ────────────────────────────────────────────────

def test_cov_e2e_gross_margin_case_unchanged():
    """基线不得变：月营收5万 - 租金8000 - 变动(5万×0.4=2万) = 2.2万；
    展示层 gross_margin_percent 仍是百分数 60。"""
    cm = _cm("月营收50000元，月租金8000元，毛利率60%")
    assert cm["monthly_profit"] == 22000.0, cm
    assert cm["gross_margin_percent"] == 60.0, cm


def test_cov_e2e_shorthand_and_fraction():
    """「月营收5万，月租金1万5，食材成本占4成」→ 租金1.5万、变动率0.4、利润1.5万。"""
    cm = _cm("月营收5万，月租金1万5，食材成本占4成")
    assert cm["monthly_revenue"] == 50000.0, cm
    assert cm["monthly_profit"] == 15000.0, cm


def test_cov_e2e_noodle_shop_daily_wording():
    """面馆日常说法：每碗18元 + 日均200碗 + 食材成本占4成。
    营收 200×18×30 = 108000；利润 108000 − 8000 − 43200 = 56800。"""
    cm = _cm("开面馆，月租金8000，每碗18元，日均卖200碗，食材成本占4成")
    assert cm["monthly_revenue"] == 108000.0, cm
    assert cm["monthly_profit"] == 56800.0, cm


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
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
            print(f"ERROR {t.__name__}: {e!r}")
            failed += 1
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)
