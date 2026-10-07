"""连接层失败预算护栏：超时参数齐备 + DSN 尊重 + 实测快失败。

背景（2026-10-07 存储加固审查 S1/Z1，P0）：
`psycopg.connect(url, autocommit=True)` 原先没有任何超时。PG 半开 / wedged 时，一次
卡住的查询会永久占住 `PostgresStore._conn_lock`（`_execute` 全程持锁），全部任务
API 连 /health 一起冻死——本地单用户场景下唯一能把「部分失败」放大成
「整体不可用」的点。libpq 默认连接超时可到 75s 以上，语句超时更是无限。

护栏四条：
1. 无 DSN 覆盖时，超时与 keepalive 必须齐备；
2. DSN 里显式给出的同名参数必须被尊重（不覆盖、不重复注入）；
3. 实测生效：连上测试库后 current_setting 必须等于我们设的值（不是"发了命令"就算）；
4. 实测快失败：不可达地址必须在预算内失败，且收敛为 StoreUnavailableError。
"""

import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from storage.local_store import (  # noqa: E402
    _CONNECT_TIMEOUT_S,
    _LOCK_TIMEOUT_MS,
    _STATEMENT_TIMEOUT_MS,
    PostgresStore,
    StoreUnavailableError,
    _pg_connect_params,
)


def test_params_include_failure_budget():
    """无 DSN 覆盖时：连接/语句/锁/闲置事务超时 + TCP keepalive 缺一不可。"""
    params = _pg_connect_params("postgresql://user@localhost:5432/db")
    assert params.get("connect_timeout") == _CONNECT_TIMEOUT_S, (
        "缺少 connect_timeout——PG 不可达时启动/请求会无限等（libpq 默认可到 75s+）"
    )
    options = params.get("options", "")
    assert f"statement_timeout={_STATEMENT_TIMEOUT_MS}" in options, (
        "缺少 statement_timeout——卡住的查询永久占住连接锁，全站冻结（Z1）"
    )
    assert f"lock_timeout={_LOCK_TIMEOUT_MS}" in options, "缺少 lock_timeout"
    assert "idle_in_transaction_session_timeout" in options, "缺少闲置事务超时"
    assert params.get("keepalives") == 1, "缺少 TCP keepalive——半开连接不会被察觉"


def test_dsn_explicit_values_win():
    """DSN 显式给出的同名参数必须被尊重：不覆盖、不重复注入。"""
    url = (
        "postgresql://user@localhost:5432/db"
        "?connect_timeout=30&options=-c%20statement_timeout%3D60000"
    )
    params = _pg_connect_params(url)
    assert "connect_timeout" not in params, "覆盖了 DSN 里的 connect_timeout（用户配置被吃掉）"
    assert "options" not in params, "覆盖了 DSN 里的 options（用户配置被吃掉）"
    # keepalive 不冲突，仍应补上
    assert params.get("keepalives") == 1


def _pg_or_skip():
    try:
        store = PostgresStore()
        store.ping()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"本机 PG 不可用，跳过实测护栏: {e}")
    return store


def test_timeouts_actually_applied_on_server():
    """实测生效：服务端 current_setting 必须等于我们设的值，而不是"命令发出去了"。"""
    store = _pg_or_skip()
    try:
        def _run(cur):
            cur.execute(
                "SELECT current_setting('statement_timeout'), current_setting('lock_timeout')"
            )
            return cur.fetchone()

        row = store._execute(_run, retry_statement=True)
        assert row[0] == f"{_STATEMENT_TIMEOUT_MS // 1000}s", (
            f"statement_timeout 未生效：服务端实际 {row[0]!r}"
        )
        assert row[1] == f"{_LOCK_TIMEOUT_MS // 1000}s", (
            f"lock_timeout 未生效：服务端实际 {row[1]!r}"
        )
    finally:
        store.close()


def test_unreachable_host_fails_within_budget():
    """实测快失败：不可达地址必须在预算内失败并收敛为 StoreUnavailableError。

    192.0.2.1 是 RFC 5737 TEST-NET-1，保证不会有人真的监听——报文被静默丢弃，
    正是"没有超时就会挂住"的形态。预算 = 两次连接尝试（首次 + 无条件重试一次）
    + 余量，远超则说明超时没生效。
    """
    store = PostgresStore(url="postgresql://nobody@192.0.2.1:5432/nodb")
    started = time.time()
    try:
        with pytest.raises(StoreUnavailableError):
            store.ping()
    finally:
        store.close()
    elapsed = time.time() - started
    assert elapsed < _CONNECT_TIMEOUT_S * 2 + 10, (
        f"不可达地址耗时 {elapsed:.1f}s，超出超时预算——connect_timeout 未生效"
    )
