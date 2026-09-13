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


def _guard_of(text):
    """取抽取结果里的守门报告（无则空结构）。"""
    return extract_params(text).get("_guard") or {}


def test_cov_e6_negative_rent_keeps_sign_and_hits_guard():
    """D1：`月租金-8000` 的负号**必须保留并交给 param_guard**，不得被抽取器静默改成 8000。

    旧行为：短关键词「月租」先命中 → after_text="金-8000" → 开头不是负号 → 符号丢失，
    静默把 -8000 变成 8000。这等于抽取器抢在 guard 之前替用户「修正」数据，
    使 guard 本来正确的 critical 校验（低于物理下限 0）永远收不到该值。
    """
    g = _guard_of("月租金-8000")
    crit = [i for i in g.get("issues", []) if i.get("level") == "critical"]
    assert crit, f"负值未触发守门 critical：{g}"
    assert crit[0]["field"] == "monthly_rent"
    assert crit[0]["value"] == -8000.0, crit[0]      # 符号保留（若被吞则变成 8000）
    assert "monthly_rent" not in _p("月租金-8000")   # 且不允许进入有效参数


def test_cov_e6_negative_word_rent_same():
    """D1：中文「负」前缀同样生效（月租金负8000）。"""
    g = _guard_of("月租金负8000")
    crit = [i for i in g.get("issues", []) if i.get("level") == "critical"]
    assert crit and crit[0]["value"] == -8000.0, g


def test_cov_e6_negative_profit_is_allowed():
    """利润可以为负（亏损），不应被 guard 判 critical —— 保留 -5000。"""
    assert _p("月利润-5000").get("monthly_profit") == -5000.0
    crit = [i for i in _guard_of("月利润-5000").get("issues", []) if i.get("level") == "critical"]
    assert not crit, f"亏损不该被判 critical：{crit}"


def test_cov_e6_range_dash_not_treated_as_sign():
    """区间分隔符不得被当负号：「每天卖100-150碗」应得正数客流，而非 -150。

    这是 D1 修复的连带回归：若负号不加「前面不得是数字」的约束，
    "100-150" 会被抽成 -150，再被 guard 判 critical 剔除 → 连正常客流都丢了。
    """
    v = _p("每天卖100-150碗").get("daily_traffic")
    assert v is not None and v > 0, f"区间被误判为负值或漏抽：{v}"


def test_cov_e6_positive_numbers_unaffected():
    """防回归：正数与金额缩写不得因负号改动而失效。"""
    assert _p("月租金8000")["monthly_rent"] == 8000.0
    assert _p("月租1万5")["monthly_rent"] == 15000.0
    assert _p("投资20万")["total_investment"] == 200000.0
    assert _p("月租2万5人")["monthly_rent"] == 20000.0


def _filled(raw):
    """走 _fill_params（含 derive 覆盖），返回用于一致性检查的 params。"""
    from tools.workflow_engine import _fill_params
    p, _src, _mixed = _fill_params(raw)
    return p


def test_cov_e7_vcr_gm_conflict_is_surfaced():
    """D2：vcr 与 gm 同时给出且矛盾时，**必须显式提示**，不得静默丢弃用户的毛利率。

    旧缺陷：_fill_params 把 gm 覆盖成 1−vcr，等到 consistency_issues 运行时矛盾已销毁
    → 用户说「毛利率 50%」，输出却变成 60%，全程无提示（静默篡改用户输入）。
    """
    from field_model import consistency_issues
    p = _filled({"monthly_rent": 8000, "daily_traffic": 150,
                 "price_per_unit": 18, "variable_cost_ratio": 0.4,
                 "gross_margin": 0.5})
    issues = consistency_issues(p)
    assert issues, "矛盾未被检出（用户毛利率会被静默丢弃）"
    assert "矛盾" in issues[0]["message"], issues[0]
    assert "50%" in issues[0]["message"] and "60%" in issues[0]["message"], issues[0]


def test_cov_e7_no_false_positive_when_consistent():
    """口径自洽（vcr=0.4 → gm=0.6）不得误报矛盾。"""
    from field_model import consistency_issues
    for raw in ({"monthly_rent": 8000, "variable_cost_ratio": 0.4, "gross_margin": 0.6},
                {"monthly_rent": 8000, "variable_cost_ratio": 0.4},
                {"monthly_rent": 8000, "gross_margin": 0.5}):
        assert consistency_issues(_filled(raw)) == [], raw


def test_cov_e7_conflict_offers_two_alignments():
    """矛盾应给出两个口径对齐方向（以 vcr 为准 / 以 gm 为准），由用户确认而非系统独断。"""
    from field_model import conflict_resolution_ops
    p = _filled({"monthly_rent": 8000, "daily_traffic": 150,
                 "price_per_unit": 18, "variable_cost_ratio": 0.4,
                 "gross_margin": 0.5})
    ops = conflict_resolution_ops(p)
    labels = [o["label"] for o in ops]
    assert len(ops) == 2, labels
    assert any("毛利率改为 60%" in l for l in labels), labels
    assert any("变动成本率改为 50%" in l for l in labels), labels


# ── E8：客单价的真实说法（D3：最高频措辞整段丢失）─────────────────────────
#
# 根因：`_extract_unit_price_alias` 只认「量词紧邻数字」（每碗18元），
# 而真实口语里量词和数字之间隔着商品名/动词，或数字在前量词在后：
#   「一碗牛肉面卖18元」「一碗卖18元」「牛肉面卖18元一碗」
# 实测这三种全部返回 {} —— 用户明明报了价，系统记不住，还回头追问「客单价」。

def test_cov_e8_price_with_product_name_and_verb():
    """「一碗牛肉面卖18元」——量词与数字之间夹商品名 + 动词「卖」。"""
    for text, exp in {
        "一碗牛肉面卖18元": 18,
        "一碗卖18元": 18,
        "一份黄焖鸡卖23元": 23,
        "一杯奶茶卖15元": 15,
    }.items():
        got = _p(text).get("price_per_unit")
        assert got == exp, f"{text} → price_per_unit={got}（期望 {exp}）"


def test_cov_e8_price_with_product_name_no_verb():
    """「一碗牛肉面18元」——无动词，仅商品名。"""
    for text, exp in {
        "一碗牛肉面18元": 18,
        "一杯拿铁28元": 28,
    }.items():
        got = _p(text).get("price_per_unit")
        assert got == exp, f"{text} → price_per_unit={got}（期望 {exp}）"


def test_cov_e8_price_quantifier_after_number():
    """「牛肉面卖18元一碗」——量词后置（数字+元+量词）。"""
    for text, exp in {
        "牛肉面卖18元一碗": 18,
        "卖18元一碗": 18,
        "定价18元一杯": 18,
    }.items():
        got = _p(text).get("price_per_unit")
        assert got == exp, f"{text} → price_per_unit={got}（期望 {exp}）"


def test_cov_e8_negative_cost_sentence_still_not_price():
    """护栏：含「成本」的金额不得被当售价（E3 护栏在新形态下仍生效）。"""
    for text in ("一碗牛肉面成本6元", "每碗成本6元", "食材成本每份8元"):
        assert _p(text).get("price_per_unit") is None, f"{text} 被误判为售价: {_p(text)}"


def test_cov_e8_negative_daily_traffic_not_price():
    """护栏：「每天卖100碗」无元/块 → 仍是客流，不是客单价。"""
    p = _p("每天卖100碗")
    assert p.get("daily_traffic") == 100, p
    assert p.get("price_per_unit") is None, p


def test_cov_e8_negative_time_period_after_money_is_not_price():
    """护栏（D3 回归）：「月租金8000元一个月」的「一个月」是时间单位，不是销售单位。"""
    for text in ("月租金8000元一个月", "房租每月8000元", "每月工资6000元一个月"):
        p = _p(text)
        assert p.get("price_per_unit") is None, f"{text} 被误判为客单价: {p}"


def test_cov_e8_negative_salary_per_person_is_not_price():
    """护栏：人均月薪（元/人）不得被形态 B 当成客单价。"""
    p = _p("每个员工6000元")
    assert p.get("price_per_unit") is None, p


def test_cov_e8_end_to_end_noodle_shop_reaches_full_params():
    """端到端：补齐后，牛肉面店多轮措辞应能凑齐客流+客单价+变动成本。"""
    p = _p("一碗牛肉面卖18元，一碗成本6元，每天卖100碗")
    assert p.get("price_per_unit") == 18, p
    assert p.get("daily_traffic") == 100, p
    assert p.get("unit_variable_cost") == 6, p


# ── E9：率字段的量纲护栏（D4：把「6元」当成变动成本率 6%）────────────────
#
# 根因：variable_cost_rate 是**率**字段，units 为 %，但兜底路径允许无单位纯数字。
# 「一碗的变动成本6元」→ rate=6.0 → 引擎按「>1 则 /100」归一 → variable_cost_ratio=0.06。
# 于是用户说的「一碗成本 6 元」被变成「变动成本率 6%」，毛利率凭空变成 94%。
# 元/块/万/千 是金额单位，量纲不符，率字段必须拒收。

def test_cov_e9_money_amount_is_not_a_rate():
    """「变动成本6元」→ 不得产出 variable_cost_rate（那是金额，不是率）。"""
    for text in ("一碗的变动成本6元", "变动成本6元", "可变成本8块"):
        p = _p(text)
        assert p.get("variable_cost_rate") is None, f"{text} 误把金额当率: {p}"
        assert p.get("variable_cost_ratio") is None, f"{text} 误把金额当率: {p}"


def test_cov_e9_unit_cost_still_extracted():
    """量纲护栏不得连正确的 unit_variable_cost 一起丢掉。"""
    assert _p("一碗的变动成本6元").get("unit_variable_cost") == 6
    assert _p("每碗成本6元").get("unit_variable_cost") == 6


def test_cov_e9_percent_rate_still_works():
    """护栏不得误伤正常百分比写法。"""
    for text, exp in {
        "变动成本率55%": 0.55,
        "变动成本占营收60%": 0.6,
    }.items():
        p = _p(text)
        got = p.get("variable_cost_ratio", p.get("variable_cost_rate"))
        assert abs(got - exp) < 1e-6, f"{text} → {got}（期望 {exp}）"


def test_cov_e9_bare_decimal_rate_still_works():
    """「变动成本率0.6」无百分号也应识别为 0.6（不得因护栏被拒）。"""
    p = _p("变动成本率0.6")
    got = p.get("variable_cost_ratio", p.get("variable_cost_rate"))
    assert abs(got - 0.6) < 1e-6, p


def test_cov_e9_gross_margin_money_not_rate():
    """毛利率同理：「毛利6元」不得变成 600% 的毛利率。"""
    assert _p("毛利6元").get("gross_margin") is None


def test_cov_e9_end_to_end_unit_cost_divided_by_price():
    """端到端：18 元售价 / 6 元单碗成本 → 变动成本率 33%，不是 6%。"""
    p = _p("一碗牛肉面卖18元，一碗成本6元")
    filled = _filled({
        "monthly_rent": 8000,
        "price_per_unit": p["price_per_unit"],
        "unit_variable_cost": p["unit_variable_cost"],
    })
    vcr = filled.get("variable_cost_ratio")
    assert abs(vcr - 6 / 18) < 1e-6, f"vcr={vcr}（期望 {6/18:.4f}）"


# ── E10：行业识别（D6 漏识别 / D7 臆断）───────────────────────────────────
#
# D6：中式快餐最主流的店名形态全部漏识别——词表里只有「面馆」，
# 而真实说法是「牛肉面店/拉面店/米粉店/饺子馆/包子铺/粥店」。
# 后果：行业落「其他」→ 拿不到餐饮模板的客流单位与默认值，
# 用户的核心场景（牛肉面店）反而享受不到行业模板。
#
# D7（反向）：成本项词汇被当成行业关键词——「包装费3000元」→ 制造。
# 用户只是报了一笔包装费，系统就给他定性成制造业。漏识别只是降级，
# 臆断是**凭空造参数**，性质更严重。

def test_cov_e10_cn_fastfood_shop_names_are_catering():
    """中式快餐主流店名必须识别为餐饮（D6）。"""
    for text in ("我想开一家牛肉面店", "开个牛肉面店", "兰州拉面店", "拉面店",
                 "米粉店", "米线店", "馄饨店", "饺子馆", "包子铺", "粥店",
                 "麻辣烫店", "黄焖鸡店", "螺蛳粉店"):
        got = extract_params(text).get("industry")
        assert got == "餐饮", f"{text} → industry={got}（期望 餐饮）"


def test_cov_e10_catering_regression_still_works():
    """既有餐饮词不得因改动而失效。"""
    for text in ("咖啡店", "奶茶店", "火锅店", "面馆", "牛肉面馆", "羊肉汤店"):
        got = extract_params(text).get("industry")
        assert got == "餐饮", f"{text} → industry={got}"


def test_cov_e10_cost_items_do_not_decide_industry():
    """D7：报一笔成本费不得把用户定性成某个行业。"""
    for text in ("包装费3000元", "每月包装2000元", "加工费5000元"):
        got = extract_params(text).get("industry")
        assert got is None, f"{text} 被臆断为 industry={got}"


def test_cov_e10_real_manufacturing_still_detected():
    """护栏：真正的制造业说法仍要识别（不得因收紧关键词而漏）。"""
    for text in ("我想开个五金加工厂", "做OEM代工的工厂", "开一家印刷厂"):
        got = extract_params(text).get("industry")
        assert got == "制造", f"{text} → industry={got}（期望 制造）"


# ── E11：客流单位用用户口径（D8「碗」被显示成「杯」）──────────────────────
#
# 行业模板只到「餐饮」粒度，餐饮默认「杯」。用户说「每天卖100碗」，
# 仪表盘却回「盈亏平衡客流 22 杯/天」—— 用户说的是碗、系统回的是杯。
# 用户自己口中的量词是最权威口径，优先于行业默认。

def test_cov_e11_user_quantifier_is_recorded():
    """抽取器记录用户口中的量词（内部键 `_traffic_unit`，不参与计算）。"""
    for text, exp in {
        "每天大概能卖100碗": "碗",
        "每天卖100杯": "杯",
        "每天100份": "份",
        "每天卖100-150碗": "碗",   # 区间写法也要取到
    }.items():
        got = extract_params(text).get("_traffic_unit")
        assert got == exp, f"{text} → _traffic_unit={got}（期望 {exp}）"


def test_cov_e11_unit_not_recorded_without_traffic():
    """没抽到客流时不记录单位（避免无客流却凭空造单位）。"""
    assert extract_params("一碗牛肉面卖18元").get("_traffic_unit") is None


def test_cov_e11_dashboard_uses_user_unit():
    """端到端：有用户量词时仪表盘用它，而非行业默认的「杯」。"""
    from router.formatter import format_response
    from tools.workflow_engine import quick_scan
    base = {"industry": "餐饮", "monthly_rent": 8000, "daily_traffic": 100,
            "price_per_unit": 18, "unit_variable_cost": 6}
    for unit, exp in (("碗", "22 碗/天"), (None, "22 杯/天")):
        payload = dict(base)
        if unit:
            payload["_traffic_unit"] = unit
        d = json.loads(quick_scan.invoke(
            {"params_json": json.dumps(payload, ensure_ascii=False)}))
        md = format_response("quick_scan", d)
        assert exp in md, f"unit={unit} 未渲染出「{exp}」：{[l for l in md.splitlines() if '盈亏平衡' in l]}"


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
