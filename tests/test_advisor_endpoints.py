"""顾问面板端点测试。

覆盖：
- GET /advisor：返回顾问面板 JSON 结构
- GET /advisor/preview：预览动作效果
- POST /advisor/apply：执行动作（与 /chat「应用 A/B」同源）
- 无效 tid 返回 400
"""

import json
import pytest
from fastapi.testclient import TestClient
from web_server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def valid_tid(client):
    """创建有效任务并返回 tid。"""
    r = client.post("/tasks", json={"name": "测试任务"}, headers={"X-Requested-With": "XMLHttpRequest"})
    return r.json()["id"]


class TestGetAdvisor:
    def test_returns_200_with_valid_tid(self, client, valid_tid):
        """有效 tid 返回 200 + 完整 JSON 结构。"""
        r = client.get(f"/advisor?tid={valid_tid}")
        assert r.status_code == 200
        data = r.json()
        assert "judgment" in data
        assert "judgment_citations" in data
        assert "risks" in data
        assert "actions" in data
        assert "citations" in data
        assert "params_version" in data

    def test_invalid_tid_returns_400(self, client):
        """无效 tid 返回 400。"""
        r = client.get("/advisor?tid=invalid")
        assert r.status_code == 400

    def test_missing_tid_returns_422(self, client):
        """缺 tid 返回 422（FastAPI 标准校验错误）。"""
        r = client.get("/advisor")
        assert r.status_code == 422


class TestPreviewAdvisorAction:
    def test_returns_ok_for_valid_op(self, client, valid_tid):
        """有效 op 返回 ok=true + preview。"""
        op = json.dumps({"propose": "set", "field": "monthly_rent", "value": 12000})
        r = client.get(f"/advisor/preview?tid={valid_tid}&op={op}")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "preview" in data

    def test_returns_reject_for_derived_field(self, client, valid_tid):
        """派生字段 op 被拒绝。"""
        op = json.dumps({"propose": "set", "field": "monthly_fixed_cost", "value": 30000})
        r = client.get(f"/advisor/preview?tid={valid_tid}&op={op}")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False

    def test_invalid_tid_returns_400(self, client):
        """无效 tid 返回 400。"""
        op = json.dumps({"propose": "set", "field": "monthly_rent", "value": 12000})
        r = client.get(f"/advisor/preview?tid=invalid&op={op}")
        assert r.status_code == 400

    def test_invalid_op_format_returns_400(self, client, valid_tid):
        """op 格式错误返回 400。"""
        r = client.get(f"/advisor/preview?tid={valid_tid}&op=not_json")
        assert r.status_code == 400


class TestApplyAdvisorAction:
    def test_returns_ok_for_valid_op(self, client, valid_tid):
        """有效 op 返回 ok=true + applied=true。"""
        op = {"propose": "set", "field": "monthly_rent", "value": 12000}
        r = client.post(f"/advisor/apply?tid={valid_tid}", json={"op": op}, headers={"X-Requested-With": "XMLHttpRequest"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["applied"] is True

    def test_returns_reject_for_derived_field(self, client, valid_tid):
        """派生字段 op 被拒绝。"""
        op = {"propose": "set", "field": "monthly_fixed_cost", "value": 30000}
        r = client.post(f"/advisor/apply?tid={valid_tid}", json={"op": op}, headers={"X-Requested-With": "XMLHttpRequest"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert data["applied"] is False

    def test_invalid_tid_returns_400(self, client):
        """无效 tid 返回 400。"""
        op = {"propose": "set", "field": "monthly_rent", "value": 12000}
        r = client.post(f"/advisor/apply?tid=invalid", json={"op": op}, headers={"X-Requested-With": "XMLHttpRequest"})
        assert r.status_code == 400

    def test_missing_op_returns_400(self, client, valid_tid):
        """缺 op 返回 400。"""
        r = client.post(f"/advisor/apply?tid={valid_tid}", json={}, headers={"X-Requested-With": "XMLHttpRequest"})
        assert r.status_code == 400
