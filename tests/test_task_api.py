"""任务 CRUD API 契约测试（Task 4）。

运行（无需 pytest）：.venv/bin/python3 tests/test_task_api.py

**隔离**：把 web_server 的 store 替换为内存版，不污染真实 PG 库。

注意（2026-10-07）：本文件的打桩**必须在模块测试结束后还原**。此前它是模块级赋值
且从不还原，泄漏到同一次 pytest 会话里后续所有用例——依赖真实 store 接线的用例
（如 /health 的存储诊断）会拿到假后端，诊断恒为空（跨测试污染，本文件已加还原）。
"""
import sys
import os
import json

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from fastapi.testclient import TestClient

# web_server 导入时会 os.chdir 到 src/，导入完成后恢复仓库根 cwd
_saved = os.getcwd()
import web_server
os.chdir(_saved)

from storage.local_store import MemoryStore, reset_store_for_tests

# 用内存 store 隔离测试（共享单例，避免 create/list 用不同实例）
reset_store_for_tests()
_test_store = MemoryStore()


@pytest.fixture(autouse=True, scope="module")
def _patch_web_server_get_store():
    """在本模块用例期间把 web_server.get_store 换成内存版，跑完还原。

    必须是 fixture 而非模块级赋值：模块级赋值发生在 pytest **收集期**（导入测试
    文件时），会立刻污染同一次会话里所有其它用例——依赖真实 store 接线的用例
    （如 /health 的存储诊断）会拿到假后端、诊断恒为空，且顺序无关地必现。
    """
    original = web_server.get_store
    web_server.get_store = lambda: _test_store
    try:
        yield
    finally:
        web_server.get_store = original

client = TestClient(web_server.app)
_XHR = {"X-Requested-With": "XMLHttpRequest"}


def test_create_and_list_task():
    r = client.post("/tasks", json={"name": "我的咖啡店"}, headers=_XHR)
    assert r.status_code == 200
    tid = r.json()["id"]
    assert r.json()["name"] == "我的咖啡店"
    r2 = client.get("/tasks")
    assert r2.status_code == 200
    assert any(t["id"] == tid and t["name"] == "我的咖啡店" for t in r2.json())


def test_default_task_name():
    r = client.post("/tasks", json={}, headers=_XHR)
    assert r.status_code == 200
    assert r.json()["name"] == "新任务"


def test_rename_task():
    tid = client.post("/tasks", json={"name": "旧名"}, headers=_XHR).json()["id"]
    r = client.put(f"/tasks/{tid}/rename", json={"name": "新名"}, headers=_XHR)
    assert r.status_code == 200
    tasks = client.get("/tasks").json()
    assert next(t["name"] for t in tasks if t["id"] == tid) == "新名"


def test_messages_roundtrip():
    tid = client.post("/tasks", json={"name": "T"}, headers=_XHR).json()["id"]
    assert client.get(f"/tasks/{tid}/messages").json() == []
    # 通过 chat 写入（当前 chat 未接 task 持久化前，先直接走 store）
    from storage.local_store import get_store
    store = web_server.get_store()
    store.add_message(tid, "user", "月租金15000")
    store.add_message(tid, "assistant", "分析如下")
    msgs = client.get(f"/tasks/{tid}/messages").json()
    assert msgs[0]["content"] == "月租金15000"


def test_soft_delete():
    tid = client.post("/tasks", json={"name": "删"}, headers=_XHR).json()["id"]
    r = client.delete(f"/tasks/{tid}", headers=_XHR)
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert tid not in {t["id"] for t in client.get("/tasks").json()}


def test_health_reports_store_backend():
    h = client.get("/health").json()
    assert "store_backend" in h
    assert h["store_backend"] == "MemoryStore"


if __name__ == "__main__":
    # 手动运行（非 pytest）时 fixture 不生效，这里显式打桩——否则会写真实 PG 库
    _orig = web_server.get_store
    web_server.get_store = lambda: _test_store
    funcs = sorted(
        (n, f) for n, f in globals().items()
        if n.startswith("test_") and callable(f)
    )
    passed = failed = 0
    try:
        for name, fn in funcs:
            try:
                fn()
                print(f"  PASS {name}")
                passed += 1
            except AssertionError as e:
                print(f"  FAIL {name}: {e}")
                failed += 1
            except Exception as e:  # noqa: BLE001
                print(f"  ERROR {name}: {e!r}")
                failed += 1
    finally:
        web_server.get_store = _orig
    print(f"==== {passed} passed, {failed} failed ====")
    sys.exit(1 if failed else 0)
