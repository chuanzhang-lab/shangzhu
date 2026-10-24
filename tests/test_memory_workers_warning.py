"""M-01 部署形态护栏：STORE_BACKEND=memory + 多 worker 必须启动告警。

背景（2026-10 线上事故根因，probe_zh_extract.py Part 3 实证）：
演示实例托管平台向 uvicorn 注入 WEB_CONCURRENCY>1，每个 worker 持有独立
MemoryStore/SessionState——同一会话的第 N 轮请求落到另一个 worker 时参数
全丢（用户第二轮「分析」时 params={}，客单价 18 消失）。单进程 + file 档
同链路 5 轮全累积（Part 2），代码无辜，纯部署形态问题。

规则：
1. warn_memory_multiworker()：STORE_BACKEND=memory 且 WEB_CONCURRENCY 或
   UVICORN_WORKERS > 1 → 返回告警文案并落 WARNING 日志；单 worker 或
   file/pg 档 → 返回 None（静默）。
2. /health 暴露 web_concurrency 字段——远程即可确认部署形态，不必再靠
   指纹反推（本周查线上形态的弯路）。
3. DEPLOY.md startCmd 必须钉死 WEB_CONCURRENCY=1（部署契约，防止平台
   默认注入多 worker 时无人察觉）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))


def _ws():
    import web_server as ws
    return ws


def test_memory_multiworker_warns(monkeypatch, caplog):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    ws = _ws()
    with caplog.at_level("WARNING"):
        msg = ws.warn_memory_multiworker()
    assert msg is not None, "memory+多worker 必须返回告警文案"
    assert "worker" in msg
    assert any("worker" in r.getMessage() for r in caplog.records), (
        "告警必须落日志（托管平台只看得到日志）"
    )


def test_memory_single_worker_silent(monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.delenv("UVICORN_WORKERS", raising=False)
    assert _ws().warn_memory_multiworker() is None


def test_multiworker_file_backend_silent(monkeypatch):
    """file/pg 档多 worker 不丢数据（磁盘/PG 共享），不得告警。"""
    monkeypatch.setenv("STORE_BACKEND", "file")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    assert _ws().warn_memory_multiworker() is None


def test_uvicorn_workers_env_also_triggers(monkeypatch):
    """UVICORN_WORKERS 是 uvicorn CLI 的等价入口，同样要检测。"""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.setenv("UVICORN_WORKERS", "3")
    assert _ws().warn_memory_multiworker() is not None


def test_health_reports_web_concurrency(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    ws = _ws()
    tc = TestClient(ws.app)
    r = tc.get("/health")
    assert r.status_code == 200
    assert "web_concurrency" in r.json(), (
        "/health 必须暴露 web_concurrency——远程确认部署形态的通道"
    )


def test_deploy_startcmd_pins_single_worker():
    """部署契约护栏：startCmd 钉死 WEB_CONCURRENCY=1，防止平台注入多 worker。"""
    with open(os.path.join(ROOT, "DEPLOY.md"), encoding="utf-8") as f:
        text = f.read()
    assert "WEB_CONCURRENCY=1" in text, (
        "DEPLOY.md startCmd 必须含 WEB_CONCURRENCY=1（M-01 部署契约）"
    )
