"""追问-回答回环端到端测试（fix-followup-swallow-20261015）。

覆盖的缺陷（取证见 .workbuddy/reports/2026-10-14-cn-followup-swallow-forensics.md）：
AI 的追问由「💡 AI 解读」按钮触发（POST /analysis/advice，app.js:1071），
而用户的回答进 POST /chat——分属两个端点，此前中间无桥：

    追问端 /analysis/advice →（无状态）→ 回答端 /chat
    extract_params={} + detect_intent=chitchat + 无 pending
    → steward → advice 空 → 兜底话术「本工作台专注…请告诉我项目参数」

用户刚答完追问却被告知「请告诉我项目参数」，stage / analysis_months 100% 被吞。

本文件锁定三层修复：
1. /chat 步骤 1.7：pending 存在时用 extract_named_params 定向捕获回答 → 合并 → 重放
   上一轮分析意图重算（不再退回 chitchat 兜底）；
2. 兜底话术条件化三分层（有 pending 重述 / 有 base 给摘要 / 空会话原话术）；
3. 超时分层口径防呆：ADVISE(8.0, chitchat 默认) 与 ADVICE(240.0, 解读显式) 不得被误删。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# web_server 导入时会 os.chdir 到 src/，导入完成后恢复（同 test_web_server_robustness）
_saved = os.getcwd()
import web_server as ws  # noqa: E402
os.chdir(_saved)

from fastapi.testclient import TestClient  # noqa: E402
from session_state import (  # noqa: E402
    set_pending_question,
    get_pending_question,
    clear_pending_question,
    reset_state,
)

import llm_advisor  # noqa: E402

_client = TestClient(ws.app)
_XHR = {"X-Requested-With": "XMLHttpRequest"}

_CASHFLOW_TURN = "牛肉面店月租8000，人工2人各4000，客单价25，日均客流150，算一下现金流"
_FALLBACK_GENERIC = "本工作台专注创业项目结构化分析"


def _chat(content, tid):
    return _client.post(
        "/chat", json={"messages": [{"role": "user", "content": content}],
        "thread_id": tid}, headers=_XHR)


def _advice(tid, ai_advice_block, asked_params=None):
    """模拟「💡 AI 解读」按钮：LLM 追问（meta 带 asked_question/asked_params）。

    ai_advice_block 只提供 analysis_id / params_version 做 stale 校验；
    追问语义由 asked_params 注入（真实链路来自 llm_advisor.advise 的 meta）。
    """
    saved = ws.llm_advise
    try:
        meta = {"asked_question": True}
        if asked_params:
            meta["asked_params"] = asked_params
        payload = {"text": "还差两项：经营阶段？分析周期看几个月？", "ops": [], "meta": meta}
        ws.llm_advise = lambda scan, user_text="", session_snapshot=None, context=None: payload
        return _client.post("/analysis/advice", json={
            "thread_id": tid,
            "analysis_id": ai_advice_block.get("analysis_id"),
            "params_version": ai_advice_block.get("params_version"),
        }, headers=_XHR)
    finally:
        ws.llm_advise = saved


def _empty_steward():
    """steward 返回空（无 key / 无可解读内容）——兜底话术触发条件。"""
    ws.llm_advise = lambda scan, user_text="", session_snapshot=None, context=None: {"text": "", "ops": []}


# ── 1. MRE：追问 → 回答 → 重算（治本二）─────────────────────────────────

def test_followup_answer_captured_and_recomputed():
    """两轮 MRE：现金流 → AI 追问 stage/analysis_months → 回答 → 按新参数重算。"""
    tid = "followup-e2e"
    reset_state(tid)

    r1 = _chat(_CASHFLOW_TURN, tid)
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["mode"] == "structured", b1
    assert b1["intent"] == "cashflow", b1

    # 追问端：LLM 提问 → 挂 pending_question
    adv = _advice(tid, b1["ai_advice"], asked_params=["stage", "analysis_months"])
    assert adv.status_code == 200
    assert adv.json()["status"] == "ok", adv.json()
    pq = get_pending_question(tid)
    assert pq and set(pq["params"]) == {"stage", "analysis_months"}, pq

    # 回答端：这句话在修复前是 chitchat + 空抽取 → 被兜底吞掉
    r3 = _chat("稳定经营，看6个月", tid)
    assert r3.status_code == 200
    b3 = r3.json()
    assert b3["mode"] == "structured", f"回答仍被吞（落 steward）: {b3}"
    assert b3["intent"] == "cashflow", f"未重放上一轮分析意图: {b3}"
    assert "已收到你的回答" in b3["content"], b3["content"]
    params = b3.get("params") or {}
    assert params.get("stage") == "稳定经营", params
    assert params.get("analysis_months") == 6, params
    assert get_pending_question(tid) is None, "答完后 pending 未清"


# ── 2. 部分回答：pending 降级保留 ───────────────────────────────────────

def test_partial_answer_degrades_pending():
    """只答了一项 → 未答字段留在 pending（重算不得把降级态抹掉）。"""
    tid = "followup-partial"
    reset_state(tid)
    r1 = _chat(_CASHFLOW_TURN, tid)
    assert r1.json()["mode"] == "structured"
    _advice(tid, r1.json()["ai_advice"], asked_params=["stage", "analysis_months"])

    r2 = _chat("稳定经营", tid)
    b2 = r2.json()
    assert b2["mode"] == "structured", b2
    assert "分析月数" not in b2["content"], f"确认行不应含未答字段: {b2['content'][:120]}"
    pq = get_pending_question(tid)
    assert pq is not None and pq["params"] == ["analysis_months"], pq

    r3 = _chat("6个月", tid)
    b3 = r3.json()
    assert b3["mode"] == "structured", b3
    assert (b3.get("params") or {}).get("analysis_months") == 6, b3
    assert get_pending_question(tid) is None, "两项答完后 pending 应清空"


# ── 3. 兜底话术三分层 ───────────────────────────────────────────────────

def test_fallback_three_tiers():
    """chitchat 且 advice 空：有 pending 重述 / 有 base 给摘要 / 空会话原话术。"""
    saved = ws.llm_advise
    try:
        # ① 空会话：原通用引导话术逐字保留
        _empty_steward()
        reset_state("fb-empty")
        c = _chat("你好", "fb-empty").json()["content"]
        assert c.startswith(_FALLBACK_GENERIC), c

        # ② 有 base 无 pending：给参数摘要，不再说「请告诉我项目参数」
        _empty_steward()
        tid = "fb-base"
        reset_state(tid)
        assert _chat("奶茶店月租金1万员工2人工资各5000客单价15日售50杯", tid).json()["mode"] == "structured"
        _empty_steward()
        c = _chat("你好", tid).json()["content"]
        assert "这句我还在学习怎么答" in c, c
        assert _FALLBACK_GENERIC not in c, c

        # ③ 有 pending：重述追问（字段级提示）
        _empty_steward()
        set_pending_question(tid, ["stage", "analysis_months"], "advice")
        c = _chat("你好", tid).json()["content"]
        assert "接着上面的问题" in c, c
        assert "经营阶段（爬坡期/稳定经营/准备扩张）" in c, c
        assert "比如「6个月」" in c, c
    finally:
        ws.llm_advise = saved
        clear_pending_question("fb-base")


# ── 4. pending 不干扰正常改参；新分析使旧追问过期 ─────────────────────────

def test_pending_does_not_disturb_normal_merge():
    """pending 不命中时回环不介入；新的结构化分析清掉过期 pending。"""
    tid = "followup-normal"
    reset_state(tid)
    _chat(_CASHFLOW_TURN, tid)
    set_pending_question(tid, ["stage"], "advice")

    r = _chat("月营收改成6万", tid)
    b = r.json()
    assert b["mode"] == "structured", b
    assert (b.get("params") or {}).get("monthly_revenue") == 60000.0, b
    # 正常改参句不含被追问字段 → 回环不介入（无确认行）
    assert "已收到你的回答" not in b["content"], b["content"][:120]
    # 新分析产生 → 旧追问过期
    assert get_pending_question(tid) is None


# ── 4.5 答了但被守门拦下：追问必须保留 ───────────────────────────────────

def test_guard_blocked_answer_keeps_pending():
    """「答了但值不合法」≠「没答」：横幅照出，pending 必须保留继续追问。"""
    saved = ws.llm_advise
    try:
        _empty_steward()
        tid = "followup-blocked"
        reset_state(tid)
        _chat("牛肉面店月租8000，人工2人各4000，客单价25，日均客流150", tid)
        set_pending_question(tid, ["avg_salary"], "advice")

        r = _chat("人均工资30", tid)  # 低于软界 1/10 → CRITICAL 拦截
        b = r.json()
        assert b["mode"] == "structured", b
        assert "需确认" in b["content"], "应出守门横幅告知被拦"
        pq = get_pending_question(tid)
        assert pq is not None and pq["params"] == ["avg_salary"], \
            f"被拦的答案应继续追问，实际 pending={pq}"

        # 用户改口给合法值 → 落地，pending 清空
        _empty_steward()
        r2 = _chat("人均工资6000", tid)
        assert r2.json()["mode"] == "structured"
        assert get_pending_question(tid) is None
    finally:
        ws.llm_advise = saved
        clear_pending_question("followup-blocked")


# ── 5. 超时分层口径防呆（条目⑧）───────────────────────────────────────

def test_advise_timeout_two_tiers_intact():
    """ADVISE(8.0) / ADVICE(240.0) 两个常量都必须存在——只差一个字母，
    历史上误判「8s 是死代码」删掉它，chitchat 全线 NameError。"""
    assert ws._LLM_ADVISE_TIMEOUT == 8.0
    assert ws._LLM_ADVICE_TIMEOUT == 240.0
    assert float(llm_advisor._LLM_TIMEOUT) > float(ws._LLM_ADVICE_TIMEOUT)

    captured = {}
    saved = ws._advise_with_timeout

    async def _spy(*args, timeout=None, **kwargs):
        captured["timeout"] = timeout
        return {"text": "", "ops": []}

    tid = "timeout-tier"
    ws._advise_with_timeout = _spy
    try:
        _chat("随便聊聊", tid)
        assert captured["timeout"] is None, "chitchat 应走默认档（_LLM_ADVISE_TIMEOUT=8s）"
    finally:
        ws._advise_with_timeout = saved


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
