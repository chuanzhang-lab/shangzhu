"""M-07 契约测试：NL 确认层——不确认不进引擎；跳过开关生效（2026-10）。

背景（执行简报「五个不许」第二条 / 事故 2026-10-03）：用户从没输入过
「员工80人」，系统却 ack 说收到了——抽取结果无声进引擎的体验必须封死。
确认层默认开（产品口径：前端默认发送 nl_confirm=true）；后端字段显式
opt-in（None=未声明 → 旧调用方走原合并路径，API 面零回归）。

验收（计划 M-07 行）：抽取结果 → 表单预填 +「确认开算」→ PUT；
不确认不进引擎；跳过开关生效。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from fastapi.testclient import TestClient  # noqa: E402

XHR = {"X-Requested-With": "XMLHttpRequest"}


def _client():
    import web_server as ws
    return TestClient(ws.app)


def _mk_task(tc):
    r = tc.post("/tasks", json={"name": "m07契约"}, headers=XHR)
    assert r.status_code == 200, f"建任务失败: {r.status_code} {r.text}"
    return r.json()["id"]


def _chat(tc, tid, text, nl_confirm=None):
    body = {"messages": [{"role": "user", "content": text}], "task_id": tid}
    if nl_confirm is not None:
        body["nl_confirm"] = nl_confirm
    r = tc.post("/chat", json=body, headers=XHR)
    assert r.status_code == 200, f"/chat 失败: {r.status_code} {r.text[:300]}"
    return r.json()


def _task_params(tc, tid):
    r = tc.get("/tasks", headers=XHR)
    for t in r.json():
        if t["id"] == tid:
            return t.get("params") or {}
    return None


def test_confirm_on_抽取不进引擎():
    """nl_confirm=true：抽取结果返回 pending_params，引擎/任务快照都不含它。"""
    tc = _client()
    tid = _mk_task(tc)
    resp = _chat(tc, tid, "客单价15元", nl_confirm=True)
    assert resp.get("confirm_required") is True, f"未进确认层: {sorted(resp.keys())}"
    assert resp.get("pending_params") == {"price_per_unit": 15}, \
        f"pending_params 不符: {resp.get('pending_params')}"
    # 引擎现值（响应 params）与任务快照都不许含未确认值
    assert resp.get("params", {}).get("price_per_unit") is None
    snap = _task_params(tc, tid)
    assert snap is not None and snap.get("price_per_unit") is None, \
        f"未确认值竟落库: {snap}"


def test_confirm_on_确认经PUT落库():
    """确认动作 = PUT（唯一写入口）；落库后同值 NL 不再拦。"""
    tc = _client()
    tid = _mk_task(tc)
    resp = _chat(tc, tid, "客单价15元", nl_confirm=True)
    assert resp.get("confirm_required") is True
    r = tc.put(f"/tasks/{tid}/params", json={"params": resp["pending_params"]}, headers=XHR)
    assert r.status_code == 200 and r.json().get("ok"), f"PUT 确认失败: {r.text[:300]}"
    snap = _task_params(tc, tid)
    assert snap is not None
    assert snap.get("price_per_unit") == 15, f"确认后未落库: {snap}"
    # 同值 NL 再来一轮：无差异 → 直通原路径，不进确认层
    resp2 = _chat(tc, tid, "客单价15元", nl_confirm=True)
    assert not resp2.get("confirm_required"), f"同值竟再拦: {sorted(resp2.keys())}"
    assert resp2.get("params", {}).get("price_per_unit") == 15


def test_confirm_off_旧行为兼容():
    """不声明 nl_confirm（None）或显式 false：旧合并路径原样保留。"""
    tc = _client()
    tid_legacy = _mk_task(tc)
    resp = _chat(tc, tid_legacy, "客单价15元")          # 不带字段
    assert not resp.get("confirm_required"), "旧调用方被确认层劫持"
    assert resp.get("params", {}).get("price_per_unit") == 15, "旧行为（直接进引擎）丢失"

    tid_off = _mk_task(tc)
    resp2 = _chat(tc, tid_off, "客单价15元", nl_confirm=False)   # 跳过开关
    assert not resp2.get("confirm_required"), "跳过开关不生效"
    assert resp2.get("params", {}).get("price_per_unit") == 15
    snap_off = _task_params(tc, tid_off)
    assert snap_off is not None
    assert snap_off.get("price_per_unit") == 15


def test_confirm_on_多参数与industry():
    """一句话多参数全部进 pending；与现值不同的才拦（增量口径）。"""
    tc = _client()
    tid = _mk_task(tc)
    resp = _chat(tc, tid, "月租金3000元 客单价15元", nl_confirm=True)
    assert resp.get("confirm_required") is True
    pending = resp.get("pending_params") or {}
    assert pending.get("monthly_rent") == 3000 and pending.get("price_per_unit") == 15, \
        f"多参数 pending 不符: {pending}"
    # 引擎仍为空
    assert resp.get("params", {}).get("monthly_rent") is None


def test_confirm_on_无差异直通出分析():
    """现值与抽取一致时直通原路径：正常意图计算（不进确认层也不死循环）。"""
    tc = _client()
    tid = _mk_task(tc)
    r = tc.put(f"/tasks/{tid}/params", json={"params": {"monthly_rent": 3000}}, headers=XHR)
    assert r.status_code == 200
    resp = _chat(tc, tid, "月租金3000元，帮我看看现状", nl_confirm=True)
    assert not resp.get("confirm_required"), "无差异竟进确认层（会死循环）"
    assert resp.get("params", {}).get("monthly_rent") == 3000
