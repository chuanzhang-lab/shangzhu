"""store 档位护栏：STORE_BACKEND 四个档位必须照做，pg 档必须拒绝降级。

背景（2026-10-07 存储加固 S3）：
此前没有任何档位开关——想「只要 PG、不许偷偷降级」表达不了，想「这次先用文件跑
一下」也表达不了，选择权只能交给默认值链（默认值可以争论，把选项删掉是另一回事）。

护栏：
1. auto（默认）行为与档位出现前一致：PG 不可用 → 文件 store（不是直接内存）；
2. file 档：显式跳过 PG（用黑洞地址也耗时应远小于连接超时，证明真的没去连）；
3. memory 档：落内存且诊断里写明"重启即丢"；
4. pg 档 + PG 不可用：**拒绝降级**、抛 StoreUnavailableError、不往别处写数据；
5. 非法档位名：立即 ValueError（拼错不许静默退回 auto）；
6. 请求路径：存储不可用 → 503 + 可执行的修复指引（不是裸 500）。
"""

import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from storage.local_store import (  # noqa: E402
    LocalFileStore,
    MemoryStore,
    StoreUnavailableError,
    get_store,
    reset_store_for_tests,
    store_diagnostics,
)

# 必败且快败（与 conftest 同口径）
_FAIL_URL = "postgresql://nobody@127.0.0.1:1/shangzhu_test"
# 黑洞地址（RFC 5737 TEST-NET-1）：真去连要等 connect_timeout
_BLACKHOLE_URL = "postgresql://nobody@192.0.2.1:5432/nodb"


def test_auto_mode_matches_pre_switch_behaviour(tmp_path, monkeypatch):
    """auto（默认档）：PG 不可用 → 文件 store——与档位出现前的降级链完全一致。"""
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv("PGDATABASE_URL", _FAIL_URL)
    monkeypatch.setenv("LOCAL_STORE_PATH", str(tmp_path))
    reset_store_for_tests()
    try:
        assert isinstance(get_store(), LocalFileStore)
        diag = store_diagnostics()
        assert diag["mode"] == "auto"
        assert diag["degraded"] is True
    finally:
        reset_store_for_tests()


def test_file_mode_skips_pg_entirely(tmp_path, monkeypatch):
    """file 档必须跳过 PG：PG 指向黑洞地址时也应立刻返回。"""
    monkeypatch.setenv("STORE_BACKEND", "file")
    monkeypatch.setenv("PGDATABASE_URL", _BLACKHOLE_URL)
    monkeypatch.setenv("LOCAL_STORE_PATH", str(tmp_path))  # 目录口径（conftest/e2e 都这么传）
    reset_store_for_tests()
    try:
        started = time.time()
        store = get_store()
        elapsed = time.time() - started
        assert isinstance(store, LocalFileStore)
        assert elapsed < 3, f"file 档耗时 {elapsed:.1f}s——疑似仍去连了 PG（应显式跳过）"
        diag = store_diagnostics()
        assert diag["mode"] == "file"
        assert "显式选择" in (diag["degrade_reason"] or ""), "file 档未在诊断里标明是显式选择"
    finally:
        reset_store_for_tests()


def test_memory_mode_flags_data_loss(monkeypatch, tmp_path):
    """memory 档：落内存 + 诊断明说"重启即丢"（显式选择也要留痕）。"""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LOCAL_STORE_PATH", str(tmp_path))
    reset_store_for_tests()
    try:
        assert isinstance(get_store(), MemoryStore)
        diag = store_diagnostics()
        assert diag["mode"] == "memory"
        assert "重启即丢" in (diag["degrade_reason"] or "")
    finally:
        reset_store_for_tests()


def test_pg_mode_refuses_to_degrade(tmp_path, monkeypatch):
    """pg 档 + PG 不可用：拒绝降级——数据不许被悄悄写到别处。"""
    import storage.local_store as ls

    target_file = tmp_path / "local_store.json"
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("PGDATABASE_URL", _FAIL_URL)
    monkeypatch.setenv("LOCAL_STORE_PATH", str(target_file))
    reset_store_for_tests()
    try:
        with pytest.raises(StoreUnavailableError) as ei:
            get_store()
        message = str(ei.value)
        assert "拒绝降级" in message, f"pg 档未拒绝降级：{message}"
        assert "doctor.py" in message, "pg 档的报错必须给出下一步动作（体检命令）"
        assert not target_file.exists(), "pg 档竟然把数据写进了文件 store——档位语义被破坏"
        assert ls._store is None, "失败后遗留了半初始化的单例（后续调用会拿到降级后端）"
    finally:
        reset_store_for_tests()


def test_invalid_mode_fails_fast(monkeypatch):
    """拼错的档位名必须立刻报错，不许静默退回 auto。"""
    monkeypatch.setenv("STORE_BACKEND", "postgres")  # 常见拼写误区
    reset_store_for_tests()
    try:
        with pytest.raises(ValueError) as ei:
            get_store()
        assert "允许值" in str(ei.value)
    finally:
        reset_store_for_tests()


def test_env_beats_config_and_default_is_auto(monkeypatch):
    """档位优先级：env → config/storage.json → auto。"""
    from storage import dburl

    monkeypatch.delenv("STORE_BACKEND", raising=False)
    assert dburl.resolve_store_backend() == "auto"
    monkeypatch.setenv("STORE_BACKEND", "pg")
    assert dburl.resolve_store_backend() == "pg"


def test_unavailable_store_returns_503_with_actionable_message(tmp_path, monkeypatch):
    """请求路径端到端：存储不可用 → 503 + 修复指引（不是裸 500，也不是空话）。"""
    from fastapi.testclient import TestClient

    import web_server

    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("PGDATABASE_URL", _FAIL_URL)
    monkeypatch.setenv("LOCAL_STORE_PATH", str(tmp_path))
    reset_store_for_tests()
    try:
        with TestClient(web_server.app, raise_server_exceptions=False) as client:
            resp = client.get("/tasks")
        assert resp.status_code == 503, f"期望 503，实际 {resp.status_code}"
        assert "doctor.py" in resp.json()["error"]
    finally:
        reset_store_for_tests()
