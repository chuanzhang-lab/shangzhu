"""测试 CORS 白名单配置 + POST 防护中间件。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from fastapi.testclient import TestClient

# 禁止 env 中残留 PGDATABASE_URL（避免 TestClient 触发 PG 连接）
os.environ.pop("PGDATABASE_URL", None)
os.environ.pop("LONGCAT_API_KEY", None)
os.environ.pop("DEEPSEEK_API_KEY", None)


def _make_client():
    """创建 TestClient，跳过 lifespan 触发的 PG 探测。"""
    import importlib
    # 阻止 lifespan 中的 get_store() 被触发——直接 mock 掉
    import web_server as ws
    orig = ws.get_store
    ws.get_store = lambda: type("S", (), {"close": lambda: None})()
    try:
        return TestClient(ws.app)
    finally:
        ws.get_store = orig


def test_cors_blocks_evil_origin():
    """恶意 Origin 不应被放行。"""
    client = _make_client()
    r = client.get("/health", headers={
        "Origin": "https://evil.example.com",
        "Access-Control-Request-Method": "GET",
    })
    # CORS 中间件应不包含 evil origin
    acao = r.headers.get("access-control-allow-origin", "")
    assert acao != "https://evil.example.com", f"CORS allows evil origin: {acao}"


def test_cors_allows_whitelisted():
    """白名单 Origin 应被放行。"""
    client = _make_client()
    r = client.get("/health", headers={
        "Origin": "http://localhost:8080",
        "Access-Control-Request-Method": "GET",
    })
    acao = r.headers.get("access-control-allow-origin", "")
    assert "localhost" in acao, f"CORS doesn't allow localhost: {acao}"


def test_cors_allows_service_default_port():
    """白名单必须覆盖服务默认端口——守护 README / start.sh / web_server 三方端口一致性。

    历史缺陷：服务默认端口是 8081，CORS 白名单却只写 8080，换端口后跨源调用被拦。
    """
    import web_server as ws
    port = os.environ.get("PORT", "8081")
    assert f"http://127.0.0.1:{port}" in ws._ALLOWED_ORIGINS, (
        f"服务默认端口 {port} 不在 CORS 白名单: {ws._ALLOWED_ORIGINS}"
    )
    assert f"http://localhost:{port}" in ws._ALLOWED_ORIGINS


def test_post_requires_xhr():
    """POST 请求缺少 X-Requested-With 头时返回 403。"""
    client = _make_client()
    r = client.post("/tasks", json={"name": "x"})
    assert r.status_code == 403, f"POST without X-Requested-With got {r.status_code}: {r.text}"
    assert "X-Requested-With" in r.text


def test_post_with_xhr_works():
    """POST 带 X-Requested-With 头应正常处理。"""
    client = _make_client()
    r = client.post("/tasks", json={"name": "xhr-task"}, headers={"X-Requested-With": "XMLHttpRequest"})
    # 500 是允许的（可能 mock store 报错），但不应是 403
    assert r.status_code != 403, f"POST with X-Requested-With blocked: {r.status_code}"


if __name__ == "__main__":
    test_cors_blocks_evil_origin()
    print("test_cors_blocks_evil_origin: PASS")
    test_cors_allows_whitelisted()
    print("test_cors_allows_whitelisted: PASS")
    test_cors_allows_service_default_port()
    print("test_cors_allows_service_default_port: PASS")
    test_post_requires_xhr()
    print("test_post_requires_xhr: PASS")
    test_post_with_xhr_works()
    print("test_post_with_xhr_works: PASS")
    print("\nAll CORS config tests passed.")
