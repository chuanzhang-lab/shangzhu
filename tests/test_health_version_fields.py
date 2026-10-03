"""版本握手护栏（M-05）：/health 暴露构建指纹，前端可自证版本。

背景：2026-10-01 事故排查最大弯路是「用户页面跑着旧前端」无从自证，
只能靠口述 toast 文案定位。握手机制：页面注入 window.__PAGE_VER__（mtime
build 号）→ 与 /health 的 static_ver 比对 → 不一致弹「版本过旧」横幅。

规则：
1. /health 必须返回 static_ver（数字 build 号）与 commit（git 短 hash 或 unknown）；
2. / 渲染的 HTML 必须注入 window.__PAGE_VER__（数字，不得残留占位符）；
3. app.js 必须带 checkVersionHandshake / showVersionBanner（握手通道不断）。
"""
import os
import re
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


def test_health_has_build_fingerprint():
    d = _client().get("/health").json()
    assert "static_ver" in d, "/health 缺 static_ver——前端版本握手无真相源"
    assert str(d["static_ver"]).isdigit(), f"static_ver 应为数字 build 号，实际 {d['static_ver']!r}"
    assert "commit" in d and d["commit"], "/health 缺 commit——无法定位用户跑的是哪个提交"
    assert isinstance(d["commit"], str) and 1 <= len(d["commit"]) <= 40, f"commit 形状异常: {d['commit']!r}"


def test_html_injects_page_ver():
    html = _client().get("/").text
    m = re.search(r"window\.__PAGE_VER__='([^']*)'", html)
    assert m, "HTML 未注入 window.__PAGE_VER__——前端无从知道自己的 build 号"
    assert m.group(1).isdigit(), f"__PAGE_VER__ 应为数字 build 号，实际 {m.group(1)!r}"


def test_appjs_has_handshake_channel():
    with open(os.path.join(ROOT, "src", "web_static", "app.js"), encoding="utf-8") as f:
        src = f.read()
    assert "function checkVersionHandshake(" in src, "app.js 缺 checkVersionHandshake——握手断了"
    assert "function showVersionBanner(" in src, "app.js 缺 showVersionBanner——发现旧版本也无法提示"
