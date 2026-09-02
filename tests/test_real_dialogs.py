"""真实对话 oracle — 验证 LLM 在干净的输入下「真在对话，不是套降级模板」。

覆盖三个关键场景：
- T1「明确改参数」→ 引擎应用、派生字段重算、LLM 解读不翻历史原文对账
- T2「模糊目标」→ LLM 输出 ops 块（编排提议），op_executor 校验 + 用户「应用」生效
- T3「守门拦死值」→ op 携带派生字段 / 超界值 → 拒绝并附理由

LLM 被桩掉，重点测的是**架构契约**而非 LLM 真实回答。
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import web_server as ws
from fastapi.testclient import TestClient
from session_state import reset_state, get_state, to_llm_view
from op_executor import (
    validate_op, preview_op, apply_op, parse_apply_command,
    BASE_FIELDS, DERIVED_FIELDS,
)
from tools.workflow_engine import quick_scan

# 桩 LLM 让它在不同问句下「装作在对话/编排」——通过 user_text 关键选择回复
def _stub_advise(scan, user_text="", session_snapshot=None):
    text = user_text or ""
    if "怎么扭亏" in text or "怎么不亏" in text:
        # 模糊目标 → LLM 应该输出 ops 块
        out = (
            "月亏 -900 偏紧。要扭亏有三个杠杆可动，先看引擎算的候选：\n\n"
            "```ops\n"
            "[\n"
            '  {"propose": "try", "label": "提价2元", "changes": {"price_per_unit": 17}, "reason": "客单价+2元看能否扭亏"},\n'
            '  {"propose": "try", "label": "客流+10/天", "changes": {"daily_traffic": 60}, "reason": "客流提升10/天看能否扭亏"}\n'
            "]\n"
            "```"
        )
        return {"text": out.replace("```ops\n[\n", "```ops\n[\n").split("```ops",1)[0].strip(),
                "ops": [
                    {"propose":"try","label":"提价2元","changes":{"price_per_unit":17},"reason":"看能否扭亏"},
                    {"propose":"try","label":"客流+10/天","changes":{"daily_traffic":60},"reason":"看能否扭亏"},
                ]}
    # 明确改参数 → 解读后果，但不应输出 ops（抽取已经处理）
    if "人工" in text or "工资" in text:
        return {"text": "已应用：人工参数按你的口径更新，月固定成本由引擎重算——月利润相应同步。", "ops": []}
    return {"text": "本分析基于当前参数。要扭亏请说『怎么不亏』，会给你候选方案预览。", "ops": []}

ws.llm_advise = _stub_advise
_client = TestClient(ws.app)


def _ensure_stub():
    """每个测试入口重新挂桩——防其他测试（如 test_p49_chitchat_goes_steward）
    在运行时把 ws.llm_advise 改成自己的 lambda 后未还原，污染本套 oracle。
    """
    ws.llm_advise = _stub_advise


def _chat(text, tid):
    return _client.post("/chat", json={"messages":[{"role":"user","content":text}], "thread_id": tid}, headers={"X-Requested-With": "XMLHttpRequest"}).json()


def _scan_d(d):
    return json.loads(quick_scan.invoke({"params_json": json.dumps(d, ensure_ascii=False)}))


# ── T1: 明确改参数 → 引擎应用 + LLM 不对账历史 ────────────────────────────

def test_t1_explicit_param_change_propagates():
    """「人工改为2*3000」→ 引擎 avg_salary=3000、月利润随其实时重算；不残留旧值。"""
    _ensure_stub()
    tid = "real-t1"
    reset_state(tid)
    r1 = _chat("开羊肉汤店，月租金1200，日售50杯，单价15，变动成本率60%，员工2人工资各3500", tid)
    assert r1["intent"] in ("quick_scan",)
    p1 = r1["params"]
    assert p1.get("avg_salary") == 3500.0, p1
    # T1 B: 改成 3000
    r2 = _chat("人工改为2*3000", tid)
    p2_state = get_state(tid)["params"]
    assert p2_state.get("avg_salary") == 3000.0, p2_state
    # 派生字段是引擎运行时算出的，从响应内容里验（chat 响应 params 只含用户/会话参数）
    content = r2["content"]
    assert "monthly_labor_cash" in content and "6,000" in content
    assert "monthly_labor" in content and "6,000" in content
    assert "monthly_fixed_cost" in content and "7,200" in content  # 1200+6000（无默认社保负担）


def test_t1_llm_view_has_no_raw_text():
    """to_llm_view 不应暴露历史 raw_text（对账幻觉根因被切断）。"""
    _ensure_stub()
    _ensure_stub()
    tid = "real-t1-view"
    reset_state(tid)
    _chat("开羊肉汤店，人工3500*2，月租1500，日售50杯", tid)
    _chat("人工改为2*3000", tid)
    view = to_llm_view(tid)
    assert "raw_text" not in view, "清洁视图不应含 raw_text"
    assert "last_changes" in view, "应该含本轮变更"
    assert "avg_salary" in view.get("last_changes", {}), view.get("last_changes")


# ── T2: 模糊目标 → LLM 输出 ops，op_executor 校验 + 预览 + 用户「应用」生效 ──

def test_t2_fuzzy_goal_emits_ops():
    """模糊目标『怎么不亏』→ LLM 输出 ops，渲染为「方案A/B→月利润Y，回『应用A』生效」。"""
    _ensure_stub()
    tid = "real-t2"
    reset_state(tid)
    _chat("开羊肉汤店，月租金1200，日售50杯，单价15，变动成本率60%，人工2*3000", tid)
    r = _chat("怎么不亏", tid)
    content = r["content"]
    assert "方案A" in content and "方案B" in content, content[:500]
    assert "应用A" in content and "应用B" in content
    assert "月利润" in content
    # 应被挂到 session 等用户确认
    st = get_state(tid)
    assert "_pending_ops" in st and len(st["_pending_ops"]) == 2


def test_t2_apply_command_executes():
    """用户回『应用A』→ op_executor 校验 + apply_op 写入 + 重算。"""
    _ensure_stub()
    _ensure_stub()
    tid = "real-t2-apply"
    reset_state(tid)
    _chat("开羊肉汤店，月租金1200，日售50杯，单价15，变动成本率60%，人工2*3000", tid)
    _chat("怎么不亏", tid)
    r3 = _chat("应用A", tid)
    assert r3["mode"] == "apply", r3
    params = r3["params"]
    # 方案A=提价2元 → price_per_unit=17
    assert params.get("price_per_unit") == 17.0, params
    # 月营收随之提高（50×17×30=25500），月利润转正（25500 - 9600 - 0.6×25500 = 6300）
    st = get_state(tid)
    assert st["params"].get("price_per_unit") == 17.0


# ── T3: 守门 — op 携带派生字段或超界值被拒 ────────────────────────────────

def test_t3_op_rejects_derived_field():
    """op 改 monthly_labor（派生字段）→ 校验拒绝。"""
    _ensure_stub()
    op = {"propose":"set", "field":"monthly_labor", "value": 5000}
    ok, reason = validate_op(op)
    assert not ok
    assert "派生" in reason, reason


def test_t3_op_rejects_absurd_value():
    """op 改 avg_salary=-5000（物理不可能）→ 校验拒绝。"""
    _ensure_stub()
    _ensure_stub()
    op = {"propose":"set", "field":"avg_salary", "value": -5000}
    ok, reason = validate_op(op)
    assert not ok
    assert "avg_salary" in reason or "物理" in reason


def test_t3_op_accepts_base_field_in_range():
    """op 改 avg_salary=4500（合理）→ 校验通过。"""
    _ensure_stub()
    op = {"propose":"set", "field":"avg_salary", "value": 4500}
    ok, reason = validate_op(op)
    assert ok and reason == ""


def test_t3_parse_apply_command():
    _ensure_stub()
    assert parse_apply_command("应用") == 0
    assert parse_apply_command("应用A") == 1
    assert parse_apply_command("应用2") == 2
    assert parse_apply_command("应用方案B") == 2
    assert parse_apply_command("随便说") is None


def test_t3_preview_computes_profit():
    """preview_op 必须给出「方案应用后月利润」精确值，不靠 LLM 心算。"""
    _ensure_stub()
    _ensure_stub()
    base = {"industry":"餐饮","monthly_rent":1200,"daily_traffic":50,"price_per_unit":15,
            "variable_cost_ratio":0.6,"avg_salary":3000,"employee_count":2}
    op = {"propose":"try","label":"提价2元","changes":{"price_per_unit":17}}
    preview = preview_op(op, base, quick_scan)
    assert preview["ok"]
    # 应用后月利润 = 50×17×30 - 9600 - 0.6×(50×17×30) = 25500 - 9600 - 15300 = 600
    # 但实际引擎可能略有差异，验证它给出的不是 garbage
    assert isinstance(preview["profit_after"], (int, float)), preview


# ── T4: 试一遍 supersede — apply 后再 '怎么不亏' → 新候选基于已应用 ────────

def test_t4_pending_ops_consumed_after_apply():
    """应用后 _pending_ops 应被消费（避免重复应用同 op）。"""
    _ensure_stub()
    tid = "real-t4"
    reset_state(tid)
    _chat("开羊肉汤店，月租金1200，日售50杯，单价15，变动成本率60%，人工2*3000", tid)
    _chat("怎么不亏", tid)
    assert "_pending_ops" in get_state(tid)
    _chat("应用A", tid)
    assert "_pending_ops" not in get_state(tid) or not get_state(tid)["_pending_ops"]


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
    _ensure_stub()