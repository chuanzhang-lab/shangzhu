"""存储可见性护栏：降级必须让用户看得见（/health 字段 + 前端横幅 + 孤儿提示）。

背景（2026-10-07 存储加固审查 T2/L2/Z3）：
PG 不可用时 get_store() 会降级到本地文件 / 内存 store，但此前**只有服务端日志知道**：
/health 只暴露类型名，前端没有任何提示，用户以为数据都存进了 PG——降级成了静默分流。
另外 get_store() 只在降级当时提示孤儿数据，PG 恢复那一刻不打任何招呼，那批数据不可见。

护栏五条：
1. /health 必须暴露降级诊断字段，且不得泄漏凭据；
2. PG 不可用 → 诊断必须如实反映「已降级 + 落到哪个文件 + 原因」；
3. PG 就绪 + 存在未迁回的降级期数据 → orphan_tasks 必须 > 0（L2）；
4. 前端必须消费 store_degraded 与 persist_warning（否则服务端做了也没用）；
5. 诊断接口返回副本（外部改不动内部状态）。
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

# 必败且快败的 PG 地址（与 conftest 同口径）：用于制造"降级"场景
_FAIL_URL = "postgresql://nobody@127.0.0.1:1/shangzhu_test"

_DIAG_KEYS = (
    "store_backend",
    "store_degraded",
    "store_target",
    "store_degrade_reason",
    "store_file_path",
    "store_orphan_tasks",
    "store_write_failures",
    "store_last_write_ok",
)


def _reset_store():
    from storage.local_store import reset_store_for_tests

    reset_store_for_tests()


def test_health_exposes_store_diagnostics_without_credentials():
    """/health 必须暴露降级诊断字段，且字段里不得出现凭据。"""
    from fastapi.testclient import TestClient

    import web_server
    from storage.local_store import get_store as _real_get_store

    # 接线护栏：web_server.get_store 必须还是真实实现。若被其它测试文件打桩后未还原，
    # /health 会拿到假后端、诊断恒为空——那是跨测试污染，本用例不做兼容（暴露它）。
    assert web_server.get_store is _real_get_store, (
        "web_server.get_store 被其它测试打桩且未还原（跨测试污染）——"
        "请在其模块内用 fixture 还原"
    )

    _reset_store()
    try:
        with TestClient(web_server.app) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        for key in _DIAG_KEYS:
            assert key in body, f"/health 缺少 {key}——降级对前端不可见（T2 复发）"
        target = str(body.get("store_target") or "")
        assert "://" not in target, f"store_target 含连接串（可能带凭据）：{target!r}"
        assert "@" not in target, f"store_target 含用户名/密码：{target!r}"

        # 顺序不变量（端到端验证时抓到过真 bug）：/health 若在 get_store() 之前
        # 取诊断快照，首次请求会拿到空诊断——已降级却报 degraded=False。
        backend = body["store_backend"]
        assert body["store_degraded"] == (backend != "PostgresStore"), (
            f"诊断与后端不一致：backend={backend}, degraded={body['store_degraded']}"
            "——/health 可能取了初始化前的快照"
        )
        assert body["store_target"], "store_target 为空——诊断未在 store 初始化后取值"
    finally:
        _reset_store()


def test_degradation_is_reported_when_pg_unreachable(tmp_path, monkeypatch):
    """PG 不可达 → 诊断必须如实说明：已降级、落到哪个文件、原因是什么。"""
    from storage.local_store import LocalFileStore, get_store, store_diagnostics

    monkeypatch.setenv("PGDATABASE_URL", _FAIL_URL)
    monkeypatch.setenv("LOCAL_STORE_PATH", str(tmp_path / "local_store.json"))
    _reset_store()
    try:
        store = get_store()
        diag = store_diagnostics()
        assert isinstance(store, LocalFileStore), f"预期降级到文件 store，实际 {type(store).__name__}"
        assert diag["degraded"] is True, "降级了但 degraded=False ——前端不会提示（静默分流）"
        assert diag["backend"] == "LocalFileStore"
        assert diag["file_store_path"] == str(tmp_path / "local_store.json")
        assert diag["target"] == str(tmp_path / "local_store.json"), "降级时 target 应指向落盘文件"
        assert diag["degrade_reason"], "降级原因为空——用户无法判断为什么降级"
        assert "://" not in diag["degrade_reason"], "降级原因里带连接串（可能含凭据）"
    finally:
        _reset_store()


def test_orphan_tasks_are_reported_after_pg_recovers(tmp_path, monkeypatch):
    """PG 就绪 + 本地 JSON 里有未迁回的任务 → orphan_tasks 必须可见（L2）。

    这是「恢复那一刻也要留痕」的护栏：原始实现只在降级时提示，恢复后那批数据
    在日志与 /health 里都查不到。
    """
    from storage.local_store import get_store, store_diagnostics

    orphan_file = tmp_path / "local_store.json"
    orphan_file.write_text(
        json.dumps({
            "tasks": {"t-1": {"id": "t-1", "name": "降级期任务", "deleted_at": None}},
            "msgs": {},
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL_STORE_PATH", str(orphan_file))
    _reset_store()
    try:
        store = get_store()
        diag = store_diagnostics()
        if type(store).__name__ != "PostgresStore":
            pytest.skip("本机 PG 不可用——孤儿检测仅在 PG 就绪路径生效")
        assert diag["orphan_tasks"] == 1, (
            f"孤儿数据未上报（orphan_tasks={diag['orphan_tasks']}）——PG 恢复后那批数据不可见"
        )
        assert diag["degraded"] is False
    finally:
        _reset_store()


def test_diagnostics_returns_copy():
    """诊断接口返回副本：调用方改不动内部状态（防误改造成假观测）。"""
    from storage.local_store import store_diagnostics

    first = store_diagnostics()
    first["write_failures"] = 9999
    assert store_diagnostics()["write_failures"] != 9999


def test_frontend_consumes_store_signals():
    """前端必须消费两个服务端信号，否则后端做的是无用功。"""
    with open(os.path.join(ROOT, "src", "web_static", "app.js"), encoding="utf-8") as f:
        src = f.read()
    assert "store_degraded" in src, "前端未消费 /health 的 store_degraded——降级横幅缺失"
    assert "persist_warning" in src, "前端未消费 persist_warning——本轮未落盘用户不知道"
