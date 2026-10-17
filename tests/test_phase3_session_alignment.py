"""Phase 3 验收测试：跨轮对齐层（SessionState + 抽取修复 + LLM 接地）。

运行（无需 pytest）：.venv/bin/python3 tests/test_phase3_session_alignment.py
若装了 pytest，会被自动收集。

覆盖：
- 中文数字解析（一万二→12000 等，修旧「房租一万二」→1.0 的 bug）
- 抽取器：羊肉汤店 Turn1 / Turn2 正确抽取
- 跨轮 merge：两轮合并得到完整参数（消除「信息不全」反复误报）
- 完整仪表盘：merge 后 quick_scan 不再报不足
- 续算意图识别 / 重置命令
- SessionState 接地上下文（真实项目背景，无「成都冒菜店」幻觉）
- 业务消息路由：两轮均命中项目意图（不落 chitchat，从而触发 merge）
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from router.param_extractor import extract_params, extract_named_params, _parse_cn_number
from router.intent import detect_intent
from session_state import (
    apply_turn,
    reset_state,
    merge_params,
    is_continuation,
    is_reset_command,
    get_session_context,
    get_state,
    set_pending_question,
    get_pending_question,
    clear_pending_question,
)
from param_guard import guard_extracted
from tools.workflow_engine import quick_scan, cashflow_projection

TURN1 = "开羊肉汤店，投资20万，单价15，月营收2万，房租一万二"
TURN2 = "人工成本2人8000，固定成本2500，变动成本率40%，你再算一下"
TID = "test-phase3"


def _scan(params_dict):
    return json.loads(quick_scan.invoke({"params_json": json.dumps(params_dict, ensure_ascii=False)}))


def test_cn_number_parsing():
    cases = {
        "一万二": 12000, "一千五": 1500, "两万": 20000, "二十万": 200000,
        "一百二十万": 1200000, "一": 1, "十二": 12, "十": 10,
        "一万二千": 12000, "一万零二": 10002, "三": 3,
    }
    for s, exp in cases.items():
        got = _parse_cn_number(s)
        assert got == exp, f"{s!r} -> {got} 期望 {exp}"


def test_extract_turn1():
    p = extract_params(TURN1)
    assert p.get("industry") == "餐饮", p
    assert p.get("monthly_rent") == 12000.0, p
    assert p.get("total_investment") == 200000.0, p
    assert p.get("price_per_unit") == 15.0, p
    assert p.get("monthly_revenue") == 20000.0, p


def test_extract_turn2():
    p = extract_params(TURN2)
    assert p.get("employee_count") == 2.0, p
    assert p.get("avg_salary") == 8000.0, p
    assert p.get("monthly_expense") == 2500.0, p


def test_merge_across_turns():
    reset_state(TID)
    apply_turn(TID, extract_params(TURN1), TURN1, "餐饮")
    st = apply_turn(TID, extract_params(TURN2), TURN2, None)
    merged = st["params"]
    for k in ["industry", "monthly_rent", "total_investment", "price_per_unit",
              "monthly_revenue", "employee_count", "avg_salary", "monthly_expense"]:
        assert k in merged and merged[k] not in (None,), f"merge 缺 {k}: {merged}"


def test_full_dashboard_after_merge():
    reset_state(TID)
    apply_turn(TID, extract_params(TURN1), TURN1, "餐饮")
    st = apply_turn(TID, extract_params(TURN2), TURN2, None)
    d = _scan(st["params"])
    assert not d.get("insufficient"), f"merge 后仍报不足: {d.get('gaps')}"
    assert d["params"]["employee_count"] == 2.0
    assert d["params"]["avg_salary"] == 8000.0
    # P4-0 C1：Turn1 租金12000 + Turn2 人工16000(2×8000，无默认社保负担) 已为组件，显式「固定成本2500」
    # 与组件和 28000 矛盾 → 标矛盾而非静默取 2500（旧语义掩盖了真矛盾）
    assert d["params"]["monthly_fixed_cost"] == 28000.0, d["params"]["monthly_fixed_cost"]
    assert "矛盾" in d["param_sources"]["monthly_fixed_cost"]
    # 月营收从 Turn1 带入，未因 Turn2 缺失而丢失
    assert d["core_metrics"]["monthly_revenue"] == 20000.0


def test_merge_is_latest_wins():
    """新轮的非 None 值应覆盖旧值（用户最新输入优先）。"""
    old = {"monthly_rent": 8000, "employee_count": 3}
    new = {"monthly_rent": 12000}
    merged = merge_params(old, new)
    assert merged["monthly_rent"] == 12000
    assert merged["employee_count"] == 3  # 旧值保留


def test_continuation_detection():
    assert is_continuation("人工成本2人8000，你再算一下") is True
    assert is_continuation("重新算一次") is True
    assert is_continuation("开个奶茶店试试") is False


def test_reset_command():
    assert is_reset_command("重新开始") is True
    assert is_reset_command("换个新项目") is True
    assert is_reset_command("开羊肉汤店") is False


def test_session_grounding():
    reset_state(TID)
    apply_turn(TID, extract_params(TURN1), TURN1, "餐饮")
    apply_turn(TID, extract_params(TURN2), TURN2, None)
    ctx = get_session_context(TID)
    assert "餐饮" in ctx, ctx
    assert "200,000元" in ctx, ctx  # 总投资真实值，无编造
    assert "成都冒菜店" not in ctx  # 杜绝历史幻觉


def test_business_not_chitchat():
    # 羊肉汤店两轮都应命中项目意图（非 chitchat），从而触发 merge
    for t in (TURN1, TURN2):
        intent, _ = detect_intent(t)
        assert intent != "chitchat", f"{t!r} 被误判为 chitchat"
        assert intent in {"quick_scan", "suggest", "trend", "compare",
                          "benchmark", "market"}, intent


def test_pure_param_update_routes_to_quickscan():
    """回归：纯补参句（只给一个数值，无「开/投资/租金」等关键词）必须走
    quick_scan，否则会被误判 chitchat → 既不写 SessionState 也不重算，
    下一轮补参时本轮数据即「被遗忘」（用户在羊肉汤店第 2/3 轮踩中的坑）。"""
    for t in ("月营收20000元", "月租金8000元", "总投资加10万", "客单价改成18"):
        intent, _ = detect_intent(t)
        assert intent == "quick_scan", f"{t!r} 应为 quick_scan，实际 {intent}"


def test_three_turn_accumulation_keeps_revenue():
    """回归：第 2 轮补的月营收，在第 3 轮补租金后不得丢失。

    复现用户真实对话：
      T1 开羊肉汤店，投资20万，客单价15，员工2人
      T2 月营收20000元            ← 曾被误判 chitchat，营收未入 session
      T3 月租金8000元，怎么收支平衡  ← 此时 session 已不含营收 → 误报「信息不全」
    """
    reset_state("repro-3turn")
    t1 = "想开一家羊肉汤店,投资20万，客单价15元,员工2人,共8000元"
    t2 = "月营收20000元"
    t3 = "月租金8000元,你看怎么调整参数才能收支平衡"

    apply_turn("repro-3turn", extract_params(t1), t1, "餐饮")
    # 注意：这里直接走与 chat() 一致的「每轮都累积」逻辑
    p2 = extract_params(t2)
    if p2:
        apply_turn("repro-3turn", p2, t2, p2.get("industry"))
    p3 = extract_params(t3)
    if p3:
        apply_turn("repro-3turn", p3, t3, p3.get("industry"))

    merged = get_state("repro-3turn")["params"]
    assert merged.get("monthly_revenue") == 20000.0, f"营收丢失: {merged}"
    assert merged.get("monthly_rent") == 8000.0, f"租金丢失: {merged}"
    assert merged.get("total_investment") == 200000.0, f"投资丢失: {merged}"
    assert merged.get("employee_count") == 2.0, f"员工丢失: {merged}"

    # 完整仪表盘应可算（不再误报「信息不全」）
    d = _scan(merged)
    assert not d.get("insufficient"), f"3 轮累积后仍报不足: {d.get('gaps')}"


# ─── 独立运行入口（无需 pytest）──────────────────────────────────────────

def test_session_cleanup_limits_memory():
    # 模拟大量会话：应能正常创建，且超过上限后会自动淘汰最旧的
    import session_state as ss
    with ss._LOCK:
        original_sessions = dict(ss._SESSIONS)
        ss._SESSIONS.clear()
        original_max = ss._MAX_SESSIONS
        ss._MAX_SESSIONS = 5  # 临时调小便于验证
    try:
        for i in range(10):
            ss.get_state(f"cleanup-{i}")["params"]["x"] = i
        with ss._LOCK:
            assert len(ss._SESSIONS) <= 5
            # 最新创建的应保留
            assert "cleanup-9" in ss._SESSIONS
    finally:
        with ss._LOCK:
            ss._SESSIONS.clear()
            ss._MAX_SESSIONS = original_max
            ss._SESSIONS.update(original_sessions)


def test_raw_text_truncated():
    """多轮超长原文应被截断，防止 raw_text 无限增长。"""
    import session_state as ss
    tid = "raw-cap"
    reset_state(tid)
    chunk = "字" * 500
    for _ in range(30):
        apply_turn(tid, {"monthly_revenue": 1}, chunk)
    st = get_state(tid)
    assert len(st["raw_text"]) <= ss._MAX_RAW_TEXT_CHARS
    assert st["turn"] == 30


def test_session_stats_shape():
    stats = __import__("session_state", fromlist=["session_stats"]).session_stats()
    assert "active_sessions" in stats
    assert "max_sessions" in stats
    assert "ttl_seconds" in stats
    assert isinstance(stats["active_sessions"], int)


# ─── 追问-回答回环（fix-followup-swallow-20261015）────────────────────────
# 历史坑：stage / analysis_months 在 field_model 声明、workflow_engine 参与
# [缺失] 标注，但抽取器零覆盖 → AI 越追问，用户越答不上（回答 100% 被吞）。
# 以下用例锁定「抽取能力补齐 + 否命题护栏 + 边界」三件事。

def test_stage_extraction_and_negation():
    """stage 同义词→规范值；否命题（紧邻/过渡动词）一律不得入值。"""
    positive = [
        ("稳定经营", "稳定经营"),
        ("经营阶段选「稳定经营」", "稳定经营"),
        ("现在是爬坡期", "爬坡期"),
        ("刚开业", "爬坡期"),
        ("准备扩张", "准备扩张"),
        ("现在已经进入稳定经营期", "稳定经营"),
        ("好不容易进入稳定经营", "稳定经营"),
    ]
    for text, expect in positive:
        got = extract_params(text).get("stage")
        assert got == expect, f"{text!r} -> {got!r}，期望 {expect!r}"
    # 否命题：紧邻否定 + 否定词后接过渡动词（进入/达到/步入/处于）
    for text in ("不准备扩张", "不是稳定经营", "尚未稳定经营", "暂时不扩张",
                 "还没进入稳定经营期", "尚未达到稳定经营", "还没进入扩张期"):
        got = extract_params(text).get("stage")
        assert got is None, f"否命题被误抽: {text!r} -> {got!r}"
    # 多词同现取「最先出现」的那个，而不是同义词表的组优先顺序
    assert extract_params("选稳定经营还是爬坡期好？").get("stage") == "稳定经营"
    assert extract_params("爬坡期之后再进稳定经营").get("stage") == "爬坡期"


def test_extract_named_params_exposes_guard_blocked_fields():
    """被守门拦下的字段要从精简 _guard 透出，否则回环会把「答了」误判成「没答」。"""
    hit = extract_named_params("人均工资30", ["avg_salary"])
    assert "avg_salary" not in hit, "被拦字段不得作为可信值返回"
    assert "avg_salary" in (hit.get("_guard") or {}).get("needs_confirmation", []), hit
    # 未触守门时不带 _guard（保持只读断言的形状干净）
    clean = extract_named_params("选稳定经营，看6个月", ["stage", "analysis_months"])
    assert clean == {"stage": "稳定经营", "analysis_months": 6}, clean


def test_analysis_months_extraction_and_rejects():
    """analysis_months：语境式抽取；回本/租期等语境拒收；>60 拒收。"""
    assert extract_params("分析周期6个月").get("analysis_months") == 6
    assert extract_params("就看6个月吧").get("analysis_months") == 6
    assert extract_params("未来12个月").get("analysis_months") == 12
    # 拒收：这些「N个月」是回本/租期/合同，不是分析周期
    for text in ("回本周期6个月", "租期6个月", "合同期6个月", "回收周期6个月"):
        assert extract_params(text).get("analysis_months") is None, text
    # 上限 60：trend/cashflow 逐期循环，防巨量期数
    assert extract_params("600个月").get("analysis_months") is None
    # 裸「N个月」在通用抽取里不收（避免误抓），仅 pending 回环宽容
    assert extract_params("6个月").get("analysis_months") is None


def test_extract_named_params_allows_bare_in_pending_loop():
    """pending 回环专用抽取：整句即「N个月」也收（回答语境已由追问提供）。"""
    fields = ["stage", "analysis_months"]
    assert extract_named_params("6个月", fields) == {"analysis_months": 6}
    assert extract_named_params("稳定经营", fields) == {"stage": "稳定经营"}
    got = extract_named_params("选稳定经营，看6个月", fields)
    assert got == {"stage": "稳定经营", "analysis_months": 6}, got
    # 空字段清单 → 空结果
    assert extract_named_params("稳定经营6个月", []) == {}


def test_hedge_phrases_covered():
    """hedge（大概/大约/差不多/约/左右）句式不得再被吞，且不得十倍错值。"""
    assert extract_params("营收大概5万").get("monthly_revenue") == 50000.0
    assert extract_params("流水一个月5万").get("monthly_revenue") == 50000.0
    assert extract_params("成本率大概40%").get("variable_cost_ratio") == 0.4
    # 历史事故：毛利率「六成」被算成 0.06（十倍错值）
    assert extract_params("毛利率大概六成").get("gross_margin") == 0.6


def test_founder_count_not_employee_count():
    """「创始人数2人」不得落到 employee_count（模型无该字段即不猜）。"""
    for text in ("创始人数2人", "2个创始人"):
        p = extract_params(text)
        assert p.get("founder_count") == 2.0, f"{text!r} -> {p}"
        assert "employee_count" not in p, f"{text!r} 误落 employee_count: {p}"
    # 无数量不推断（宁缺勿填）
    assert extract_params("我是创始人") == {}


def test_guard_10x_soft_boundary_upgrade():
    """软边界 10 倍外 → CRITICAL + 待确认 + 拦截；10 倍内仍 WARNING（既有契约）。"""
    _, info_far = guard_extracted({"avg_salary": 1.0})
    assert info_far["has_critical"] is True
    assert "avg_salary" in info_far["needs_confirmation"]
    # 不猜修正值：不给 auto_fix，也不把错值放进 cleaned
    assert info_far["cleaned"] == {}

    _, info_in = guard_extracted({"avg_salary": 300.0})  # 300 在 [500/10, ...] 内
    assert info_in["has_critical"] is False
    assert info_in["cleaned"] == {"avg_salary": 300.0}
    # 既有契约不打破：employee_count=200 → 仍 WARNING（< 50×10）
    _, info_200 = guard_extracted({"employee_count": 200})
    assert info_200["has_critical"] is False


def test_continuation_hint_includes_xuan():
    """「选」是改参措辞（Direction 2 改主意权），不入词表会触发假矛盾警报。"""
    reset_state("cont-xuan")
    assert is_continuation("经营阶段选「稳定经营」") is True
    assert is_continuation("再算一下") is True
    assert is_continuation("你好") is False


def test_cashflow_consumes_analysis_months():
    """cashflow 硬编码 12 → 用户指定的分析周期（与 trend 同范式）。"""
    base = {"industry": "餐饮", "total_investment": 150000, "monthly_rent": 8000.0,
            "employee_count": 2.0, "avg_salary": 4000.0, "daily_traffic": 150.0,
            "price_per_unit": 25.0, "variable_cost_ratio": 0.4}

    def _cf(extra):
        import json
        return json.loads(cashflow_projection.invoke(
            {"params_json": json.dumps({**base, **extra}, ensure_ascii=False)}))

    assert len(_cf({}).get("schedule", [])) == 12, "未给 analysis_months 应仍 12 期"
    r6 = _cf({"analysis_months": 6})
    assert len(r6.get("schedule", [])) == 6
    assert any("分析周期：6 个月" in n for n in r6.get("notes", []))
    # 超界回退默认，防巨量期数
    assert len(_cf({"analysis_months": 600}).get("schedule", [])) == 12


def test_pending_question_lifecycle():
    """pending_question：空列表不挂；可读写；clear/reset 后消失。"""
    tid = "pending-life"
    reset_state(tid)
    get_state(tid)  # 建会话
    set_pending_question(tid, ["stage"], "advice")
    assert get_pending_question(tid) == {"params": ["stage"], "source": "advice"}
    set_pending_question(tid, ["stage", "analysis_months"], "chat")
    assert get_pending_question(tid)["params"] == ["stage", "analysis_months"]
    clear_pending_question(tid)
    assert get_pending_question(tid) is None
    # 空列表不挂（避免「追问了但没说追问什么」的空状态）
    set_pending_question(tid, [], "advice")
    assert get_pending_question(tid) is None
    # 重置会话 → 自然清除
    set_pending_question(tid, ["stage"], "advice")
    reset_state(tid)
    assert get_pending_question(tid) is None


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
            print(f"ERROR {t.__name__}: {e!r}")
            failed += 1
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)
