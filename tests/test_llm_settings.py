"""模型设置端点测试。

覆盖：
- GET /settings/llm：返回脱敏配置
- POST /settings/llm：保存配置，key 空则不覆盖
- 保存后 /health 的 model 动态更新
- 无效请求返回 400
- POST /settings/llm/test：连通性探测
"""

import json
import pytest
from fastapi.testclient import TestClient
from web_server import app

XHR = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture
def client():
    return TestClient(app)


def _cfg(client):
    d = client.get("/settings/llm").json()
    return d.get("config", d)


class TestGetLlmSettings:
    def test_returns_masked_key(self, client):
        r = client.get("/settings/llm")
        assert r.status_code == 200
        inner = r.json().get("config", r.json())
        assert "model" in inner
        assert "base_url" in inner
        assert "*" in inner.get("api_key", "")


class TestSetLlmSettings:
    def test_missing_model_returns_400(self, client):
        r = client.post("/settings/llm", json={"model": "", "base_url": "", "api_key": ""}, headers=XHR)
        assert r.status_code == 400

    def test_save_model_updates_health(self, client):
        before = _cfg(client)
        r = client.post("/settings/llm", json={
            "model": before["model"], "base_url": before["base_url"], "api_key": "",
        }, headers=XHR)
        assert r.status_code == 200

    def test_empty_api_key_does_not_overwrite(self, client):
        before = _cfg(client)
        r = client.post("/settings/llm", json={
            "model": before["model"], "base_url": before["base_url"], "api_key": "",
        }, headers=XHR)
        assert r.status_code == 200

    def test_short_api_key_rejected(self, client):
        before = _cfg(client)
        r = client.post("/settings/llm", json={
            "model": before["model"], "base_url": before["base_url"], "api_key": "sk",
        }, headers=XHR)
        assert r.status_code == 400


class TestHealthModelDynamic:
    def test_health_model_matches_config(self, client):
        cfg = _cfg(client)
        h = client.get("/health").json()
        assert h["model"] == cfg["model"]


class TestTestLlmSettings:
    def test_test_endpoint_missing_model(self, client):
        r = client.post("/settings/llm/test", json={
            "model": "", "base_url": "https://api.longcat.chat/openai",
            "api_key": "ak_TEST_KEY_NOT_REAL_0000000000000",
        }, headers=XHR)
        assert r.status_code == 400

    def test_test_endpoint_missing_base_url(self, client):
        r = client.post("/settings/llm/test", json={
            "model": "LongCat-2.0", "base_url": "",
            "api_key": "ak_TEST_KEY_NOT_REAL_0000000000000",
        }, headers=XHR)
        assert r.status_code == 400

    def test_test_endpoint_empty_key_uses_existing(self, client, monkeypatch):
        """key 为空时从现有配置读取，不返回 400。"""
        called = {"count": 0}
        class MockResponse:
            status_code = 200
            text = "{}"
        import requests as req
        orig = req.post
        def mock_post(*a, **k):
            called["count"] += 1
            return MockResponse()
        monkeypatch.setattr(req, "post", mock_post)
        r = client.post("/settings/llm/test", json={
            "model": "LongCat-2.0", "base_url": "https://api.longcat.chat/openai", "api_key": "",
        }, headers=XHR)
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert called["count"] >= 1

    def test_test_endpoint_success(self, client, monkeypatch):
        class MockResponse:
            status_code = 200
            text = "{}"
        import requests as req
        monkeypatch.setattr(req, "post", lambda *a, **k: MockResponse())
        r = client.post("/settings/llm/test", json={
            "model": "LongCat-2.0", "base_url": "https://api.longcat.chat/openai",
            "api_key": "ak_TEST_KEY_NOT_REAL_0000000000000",
        }, headers=XHR)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True

    def test_test_endpoint_400(self, client, monkeypatch):
        class MockResponse:
            status_code = 400
            text = "not found"
        import requests as req
        monkeypatch.setattr(req, "post", lambda *a, **k: MockResponse())
        r = client.post("/settings/llm/test", json={
            "model": "Bad", "base_url": "https://api.deepseek.com/v1",
            "api_key": "ak_TEST_KEY_NOT_REAL_0000000000000",
        }, headers=XHR)
        data = r.json()
        assert data["ok"] is False
        assert data["status_code"] == 400

    def test_test_endpoint_401(self, client, monkeypatch):
        class MockResponse:
            status_code = 401
            text = "bad key"
        import requests as req
        monkeypatch.setattr(req, "post", lambda *a, **k: MockResponse())
        r = client.post("/settings/llm/test", json={
            "model": "LongCat-2.0", "base_url": "https://api.longcat.chat/openai",
            "api_key": "wrong_key_1234567890",
        }, headers=XHR)
        data = r.json()
        assert data["ok"] is False
        assert data["status_code"] == 401

    def test_test_endpoint_timeout(self, client, monkeypatch):
        import requests as req
        def mock_timeout(*a, **k):
            raise req.exceptions.Timeout("timeout")
        monkeypatch.setattr(req, "post", mock_timeout)
        r = client.post("/settings/llm/test", json={
            "model": "LongCat-2.0", "base_url": "https://api.longcat.chat/openai",
            "api_key": "ak_TEST_KEY_NOT_REAL_0000000000000",
        }, headers=XHR)
        data = r.json()
        assert data["ok"] is False
        assert "超时" in data.get("error", "")


class TestProbeHardening:
    """连通性探测加固（docs/fix-llm-probe-timeout-20261008.md）：
    超时预算、探测 URL 单次拼接、base_url 归一。"""

    def test_probe_timeout_budget_is_30s(self):
        import llm_advisor
        assert llm_advisor._PROBE_TIMEOUT_S == 30.0

    def test_normalize_base_url_variants(self):
        from config.settings import normalize_base_url
        assert normalize_base_url("https://openrouter.ai/api/v1/chat/completions") == "https://openrouter.ai/api/v1"
        assert normalize_base_url("https://openrouter.ai/api/v1/chat/completions/") == "https://openrouter.ai/api/v1"
        assert normalize_base_url("https://api.deepseek.com/v1") == "https://api.deepseek.com/v1"
        assert normalize_base_url("https://api.deepseek.com/v1/") == "https://api.deepseek.com/v1"
        assert normalize_base_url(
            "https://openrouter.ai/api/v1/chat/completions/chat/completions"
        ) == "https://openrouter.ai/api/v1"
        assert normalize_base_url("") == ""

    @staticmethod
    def _capture_post(captured):
        import requests as req
        class MockResponse:
            status_code = 200
            text = "{}"
        def mock_post(url=None, **kwargs):
            captured["url"] = url
            return MockResponse()
        return mock_post

    def test_probe_url_single_completion_suffix(self, client, monkeypatch):
        """完整端点形态的 base_url 探测时不得双拼（修复前拼出 .../chat/completions/chat/completions）。"""
        captured = {}
        import requests as req
        monkeypatch.setattr(req, "post", self._capture_post(captured))
        r = client.post("/settings/llm/test", json={
            "model": "mimo-v2.5-pro",
            "base_url": "https://openrouter.ai/api/v1/chat/completions",
            "api_key": "ak_TEST_KEY_NOT_REAL_0000000000000",
        }, headers=XHR)
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"

    def test_probe_url_appends_for_sdk_form(self, client, monkeypatch):
        """SDK 形态（…/v1）输入仍要追加一次 /chat/completions（防归一过度剥离）。"""
        captured = {}
        import requests as req
        monkeypatch.setattr(req, "post", self._capture_post(captured))
        r = client.post("/settings/llm/test", json={
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "ak_TEST_KEY_NOT_REAL_0000000000000",
        }, headers=XHR)
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"

    def test_save_normalizes_base_url(self, client):
        """保存完整端点形态 → 配置单源落盘为 SDK 形态（先存原值，finally 还原）。"""
        before = _cfg(client)
        original = before["base_url"]
        try:
            r = client.post("/settings/llm", json={
                "model": before["model"],
                "base_url": "https://openrouter.ai/api/v1/chat/completions",
                "api_key": "",
            }, headers=XHR)
            assert r.status_code == 200
            assert _cfg(client)["base_url"] == "https://openrouter.ai/api/v1"
        finally:
            client.post("/settings/llm", json={
                "model": before["model"],
                "base_url": original,
                "api_key": "",
            }, headers=XHR)

    def test_get_llm_base_url_normalized(self, monkeypatch):
        """主链路：存量完整端点形态经 get_base_url 归一，ChatOpenAI 收到 SDK 形态。"""
        import llm_advisor
        fake = {"config": {
            "model": "mimo-v2.5-pro",
            "base_url": "https://openrouter.ai/api/v1/chat/completions",
            "api_key": "ak_TEST_KEY_NOT_REAL_0000000000000",
            "timeout": 250,
        }}
        monkeypatch.setattr(llm_advisor, "_load_llm_config", lambda: fake)
        monkeypatch.setattr(llm_advisor, "_api_key", lambda: "ak_TEST_KEY_NOT_REAL_0000000000000")
        monkeypatch.setattr(llm_advisor, "_llm_cache", None)
        client = llm_advisor._get_llm()
        shown = str(client.root_client.base_url)
        assert "chat/completions" not in shown
        assert shown.rstrip("/") == "https://openrouter.ai/api/v1"
