"""静态资源缓存护栏（M-02）：动态版本号 + no-cache。

背景（2026-10-01 翻译函数遮蔽事故的缓存侧根因，自 shangzhu-en 移植）：
磁盘代码修好了、护栏测试也过，用户页面却还在跑修复前的旧 app.js。
缓存侧两个帮凶，本文件钉死它们：

1. `?v=` 版本号写死（`?v=20260413a` 从第一个 commit 起从未更新）→
   改文件 URL 却不变，浏览器无从知道该换副本。
   护栏：URL 必须带按文件 mtime 生成的数字版本号，且不能残留占位符字面量。
2. `/static`、`/` 没有 Cache-Control → 走浏览器启发式新鲜度
   （≈10%×(now−Last-Modified)，数小时量级），长开标签页永不重取 JS。
   护栏：响应必须带 `Cache-Control: no-cache`（可回源走 304，不许「不回源就用旧副本」）。
"""
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


def test_index_uses_dynamic_asset_version():
    """/ 必须下发 mtime 版本号，且不残留占位符 / 旧的写死版本。"""
    html = _client().get("/").text
    for tag in ("/static/app.js?v=", "/static/app.css?v="):
        assert tag in html, f"页面缺少带版本号的资源引用: {tag}"
        ver = html.split(tag, 1)[1].split('"', 1)[0]
        assert ver.isdigit(), f"{tag} 后面不是数字版本号（拿到 {ver!r}）——_static_ver 没生效"
    assert "__APP_JS_VER__" not in html and "__APP_CSS_VER__" not in html, \
        "版本号占位符没被替换，浏览器会把字面量当 URL"
    assert "20260413a" not in html, "又回到写死的 ?v= 了：改文件不会让缓存失效"


def test_static_and_shell_no_cache():
    """/static、/ 必须强制回源校验（no-cache），否则旧标签页跑旧 JS。"""
    c = _client()
    for path in ("/", "/static/app.js"):
        cc = c.get(path).headers.get("cache-control", "")
        assert "no-cache" in cc, f"{path} 缺 Cache-Control: no-cache（当前: {cc!r}）"


def test_static_ver_reflects_mtime(tmp_path):
    """版本号跟着文件 mtime 走：文件一改 URL 必变（缓存失效的唯一真相源）。"""
    import web_server as ws

    asset = tmp_path / "app.js"
    asset.write_text("// v1", encoding="utf-8")
    old_dir = ws._STATIC_DIR
    ws._STATIC_DIR = str(tmp_path)
    try:
        v1 = ws._static_ver("app.js")
        os.utime(asset, (1_700_000_000, 1_700_000_000))
        v2 = ws._static_ver("app.js")
        assert v1 != v2, "mtime 变了版本号没变 → 改前端不会让浏览器缓存失效"
        assert ws._static_ver("no-such-file.js") == "0", "文件缺失时应回退到安全值，不吐占位符"
    finally:
        ws._STATIC_DIR = old_dir


def test_xhr_guard_still_enforced():
    """加缓存中间件不得顺手破坏 POST 的 X-Requested-With 防护（中间件叠加易错位）。"""
    r = _client().post("/tasks", json={"name": "guard"})
    assert r.status_code == 403, f"CSRF 防护被缓存中间件绕过: {r.status_code}"
