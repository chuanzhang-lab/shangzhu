"""/client-log 契约测试（M-06）：前端错误上报端点的防滥用四闸。

规则：
1. 合法 JSON → 200 {"ok": true}，且日志出现 WEBCLIENT 行（服务端可观测）；
2. 非 JSON / 非对象 → 400；
3. body 超 2KB → 400（防刷日志）；
4. message 超 500 字符被截断（防注入任意长文本）；
5. 未知字段被忽略（白名单口径）；
6. 无 X-Requested-With 也放行（sendBeacon 无法带自定义头，豁免是有意设计）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from fastapi.testclient import TestClient  # noqa: E402


def _client():
    import web_server as ws

    orig = ws.get_store
    ws.get_store = lambda: type("S", (), {"close": lambda: None})()
    try:
        return TestClient(ws.app)
    finally:
        ws.get_store = orig


def test_valid_report_logged(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="web")
    payload = {"stage": "loadTasks", "code": "TASKS_LOAD_FAILED", "message": "HTTP 500",
               "page_ver": "1727000000", "ts": "2026-10-03T12:00:00Z"}
    r = _client().post("/client-log", content=json.dumps(payload),
                       headers={"Content-Type": "application/json"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert any("WEBCLIENT" in rec.getMessage() for rec in caplog.records), \
        "上报没有落进服务端日志——前端错误仍不可观测"


def test_rejects_non_json():
    r = _client().post("/client-log", content="not-json",
                       headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_rejects_non_object():
    r = _client().post("/client-log", content=json.dumps(["a"]),
                       headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_rejects_oversize_body():
    big = json.dumps({"stage": "s", "code": "c", "message": "x" * 3000})
    r = _client().post("/client-log", content=big,
                       headers={"Content-Type": "application/json"})
    assert r.status_code == 400, "超过 2KB 的上报必须拒收（防刷日志）"


def test_message_truncated(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="web")
    payload = {"stage": "chat", "code": "CHAT_TIMEOUT", "message": "y" * 900}
    r = _client().post("/client-log", content=json.dumps(payload),
                       headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    joined = " ".join(rec.getMessage() for rec in caplog.records)
    assert "y" * 500 in joined and "y" * 501 not in joined, "message 未按 500 字符截断"


def test_unknown_fields_ignored():
    payload = {"stage": "s", "code": "c", "message": "m", "evil": "x" * 100}
    r = _client().post("/client-log", content=json.dumps(payload),
                       headers={"Content-Type": "application/json"})
    assert r.status_code == 200, "未知字段应忽略而非报错（白名单口径）"


def test_xhr_header_exempt_for_beacon():
    """sendBeacon 带不了 X-Requested-With——/client-log 必须豁免，否则观测归零。"""
    payload = {"stage": "s", "code": "c", "message": "m"}
    r = _client().post("/client-log", content=json.dumps(payload),
                       headers={"Content-Type": "application/json"})  # 无 X-Requested-With
    assert r.status_code == 200, f"/client-log 被 XHR 中间件拦截: {r.status_code}"
    # 对照：其他写接口仍受保护
    r2 = _client().post("/tasks", json={"name": "x"})
    assert r2.status_code == 403, "其他写接口的 CSRF 防护被顺手破坏了"
