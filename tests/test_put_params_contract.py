"""M-03 契约测试：PUT /tasks/{id}/params 必须复用 apply_turn_guarded。

背景（执行简报「五个不许」第一条）：历史上「另写一条简单更新路径」是本项目
bug 之源（merge 语义 / 守门归一化 / B 类覆盖 / 矛盾检测 / 版本号全部丢失）。
本契约把「复用」钉成可执行断言——尤其 variable_cost_ratio=6000 → 0.6 的
自动修正是 apply_turn_guarded 的文档化行为，裸路径的第一个牺牲品就是它。

验收（计划 M-03 行）：契约测试绿；curl 实测 200/400/403/404；旧字段
merge 保留；连续提交（PUT 与会话双写竞态契约）。
"""
import os
import sys
import uuid

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
    r = tc.post("/tasks", json={"name": "m03契约"}, headers=XHR)
    assert r.status_code == 200, f"建任务失败: {r.status_code} {r.text}"
    return r.json()["id"]


def test_put_without_xhr_403():
    """CSRF 契约：PUT 是写方法，不带 X-Requested-With 必须被中间件拒 403。"""
    tc = _client()
    tid = _mk_task(tc)
    r = tc.put(f"/tasks/{tid}/params", json={"params": {"monthly_rent": 8000}})
    assert r.status_code == 403, f"无 XHR 的 PUT 竟然放行: {r.status_code}"


def test_put_404_unknown_task():
    tc = _client()
    r = tc.put(
        f"/tasks/{uuid.uuid4()}/params",
        json={"params": {"monthly_rent": 1}},
        headers=XHR,
    )
    assert r.status_code == 404, f"不存在的任务应 404: {r.status_code} {r.text}"


def test_put_400_empty_params():
    tc = _client()
    tid = _mk_task(tc)
    r = tc.put(f"/tasks/{tid}/params", json={"params": {}}, headers=XHR)
    assert r.status_code == 400, f"空 params 应 400: {r.status_code} {r.text}"


def test_put_200_and_merge_preserved():
    """核心契约：第二次 PUT 不得清掉第一次的字段（merge 语义继承）。"""
    tc = _client()
    tid = _mk_task(tc)
    r1 = tc.put(
        f"/tasks/{tid}/params",
        json={"params": {"monthly_rent": 8000}},
        headers=XHR,
    )
    assert r1.status_code == 200, f"{r1.status_code} {r1.text}"
    assert r1.json()["params"]["monthly_rent"] == 8000

    r2 = tc.put(
        f"/tasks/{tid}/params",
        json={"params": {"avg_salary": 5000}},
        headers=XHR,
    )
    assert r2.status_code == 200
    p2 = r2.json()["params"]
    assert p2["monthly_rent"] == 8000, f"旧字段被清掉了（merge 丢失）: {p2}"
    assert p2["avg_salary"] == 5000


def test_put_reuses_guard_bclass_normalize():
    """复用铁证：variable_cost_ratio=6000 必须被守门归一为 0.6。
    新写裸路径的典型特征就是这个修正丢失（apply_turn_guarded 文档化行为）。"""
    tc = _client()
    tid = _mk_task(tc)
    r = tc.put(
        f"/tasks/{tid}/params",
        json={"params": {"variable_cost_ratio": 6000}},
        headers=XHR,
    )
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    v = r.json()["params"].get("variable_cost_ratio")
    assert v is not None and abs(v - 0.6) < 1e-9, (
        f"守门归一化丢失（6000 应修正为 0.6，实得 {v}）——PUT 没走 apply_turn_guarded"
    )


def test_put_consecutive_versions_advance():
    """竞态契约（连续提交）：版本号（Direction 4 观测位）必须随提交递增。"""
    tc = _client()
    tid = _mk_task(tc)
    r1 = tc.put(f"/tasks/{tid}/params",
                json={"params": {"monthly_rent": 8000}}, headers=XHR)
    r2 = tc.put(f"/tasks/{tid}/params",
                json={"params": {"avg_salary": 5000}}, headers=XHR)
    v1, v2 = r1.json()["params_version"], r2.json()["params_version"]
    assert v2 > v1, f"版本号未递增（{v1} → {v2}）——写入没进 apply_turn_guarded 的锁内路径"


def test_put_response_shape():
    """响应形状契约（M-05 前端表单将依赖）：ok/id/params/guard/params_version。"""
    tc = _client()
    tid = _mk_task(tc)
    r = tc.put(f"/tasks/{tid}/params",
               json={"params": {"monthly_rent": 8000}}, headers=XHR)
    body = r.json()
    for key in ("ok", "id", "params", "guard", "params_version"):
        assert key in body, f"响应缺 {key}: {body}"
    assert body["id"] == tid
    assert all(not k.startswith("_") for k in body["params"]), "内部键漏出到前端"
