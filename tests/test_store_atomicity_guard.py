"""一轮对话的原子写护栏（add_turn 契约 + 全写或全不写）。

背景（2026-10-07 存储加固审查 L1/T1，P0）：
`_persist_turn` 曾分三次调 store（2×add_message + update_params），而 store 实现是
autocommit——三个独立事务。崩在第 2 次就留下「有问无答 + params 陈旧」的半回合：
用户看到的内容与落盘的内容不一致，且没有任何痕迹（重启后才发现对话缺一条）。

护栏四条：
1. 三个实现都必须重写 add_turn（不得落到基类 NotImplementedError）；
2. PG：整轮单事务——第 3 步失败时前两步必须一起回滚（用「params 不可 JSON
   序列化」在两次 INSERT **之后**注入失败，走真实代码路径，不是 mock）；
3. 文件 store：落盘失败时内存缓存回滚、文件保持改动前内容；
4. 反证：旧的三步序列确实会留下半回合——证明本护栏测的是真东西。
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from storage.local_store import (  # noqa: E402
    BaseStore,
    LocalFileStore,
    MemoryStore,
    PostgresStore,
)


def _pg_store_or_skip():
    """取测试库 store；PG 不可用则跳过（与 tests/test_local_store.py 同口径）。"""
    try:
        store = PostgresStore()
        store.ping()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"本机 PG 不可用，跳过端到端护栏: {e}")
    return store


def test_all_impls_override_add_turn():
    """契约层：三个实现都要有真正的 add_turn，落到基类等于没实现。"""
    for cls in (MemoryStore, LocalFileStore, PostgresStore):
        assert cls.add_turn is not BaseStore.add_turn, (
            f"{cls.__name__} 未实现 add_turn——原子写契约被绕过，"
            "_persist_turn 会退化成非原子写入"
        )


def test_all_impls_write_whole_turn(tmp_path):
    """正常路径：一轮 = user + assistant 两条消息 + params 快照，三实现一致。"""
    mem = MemoryStore()
    tid = mem.create_task("内存轮次")["id"]
    mem.add_turn(tid, "月租金15000", "分析如下", {"monthly_rent": 15000}, turn=2)
    assert [m["role"] for m in mem.get_messages(tid)] == ["user", "assistant"]
    assert mem.get_task(tid)["params"] == {"monthly_rent": 15000}

    fs = LocalFileStore(path=str(tmp_path / "local_store.json"))
    tid2 = fs.create_task("文件轮次")["id"]
    fs.add_turn(tid2, "月租金15000", "分析如下", {"monthly_rent": 15000}, turn=2)
    assert [m["role"] for m in fs.get_messages(tid2)] == ["user", "assistant"]
    assert fs.get_task(tid2)["params"] == {"monthly_rent": 15000}


def test_pg_add_turn_rolls_back_on_midway_failure():
    """PG：第 3 步（params 序列化）失败时，前两条 INSERT 必须一起回滚。"""
    store = _pg_store_or_skip()
    tid = None
    try:
        tid = store.create_task("原子性护栏")["id"]
        with pytest.raises(Exception):
            # object() 不可 JSON 序列化 → UPDATE 之前抛错，正是「半回合」的注入点
            store.add_turn(tid, "月租金15000", "分析如下", {"bad": object()}, turn=1)

        assert store.get_messages(tid) == [], (
            "第 3 步失败后消息仍在库里——半回合落盘，P0（L1）复发"
        )
        assert (store.get_task(tid) or {}).get("params") == {}, "params 被部分写入"

        # 事务回滚后连接/事务状态必须干净：同一任务能正常写完整轮
        store.add_turn(tid, "月租金15000", "分析如下", {"monthly_rent": 15000}, turn=1)
        assert [m["role"] for m in store.get_messages(tid)] == ["user", "assistant"]
    finally:
        if tid:
            try:
                store.delete_task(tid)
            except Exception:  # noqa: BLE001
                pass
        store.close()


def test_file_store_add_turn_rolls_back_on_flush_failure(tmp_path):
    """文件 store：落盘失败不得污染内存缓存，文件保持改动前内容。"""
    path = tmp_path / "local_store.json"
    store = LocalFileStore(path=str(path))
    tid = store.create_task("文件原子性")["id"]
    before = path.read_text(encoding="utf-8")

    with pytest.raises(Exception):
        store.add_turn(tid, "u", "a", {"bad": object()}, turn=1)

    assert store.get_messages(tid) == [], "落盘失败后消息仍留在内存缓存"
    assert path.read_text(encoding="utf-8") == before, "落盘失败后文件内容被改动"


def test_old_three_call_sequence_would_leave_half_turn():
    """反证：旧三步序列（2×add_message + 失败 update_params）真的会留下半回合。

    这条不要求旧路径可用（_persist_turn 已改走 add_turn），而是证明上面两条
    原子性断言测的是真东西——否则「改成 add_turn」可能只是换了个写法。
    """
    store = _pg_store_or_skip()
    tid = None
    try:
        tid = store.create_task("反证半回合")["id"]
        store.add_message(tid, "user", "月租金15000", 1)
        store.add_message(tid, "assistant", "分析如下", 1)
        with pytest.raises(TypeError):
            json.dumps({"bad": object()})  # 旧路径第 3 步在这里失败（真实注入点）

        assert len(store.get_messages(tid)) == 2, (
            "旧三步序列竟然没留下半回合——本文件的原子性断言失去意义，请复核"
        )
    finally:
        if tid:
            try:
                store.delete_task(tid)
            except Exception:  # noqa: BLE001
                pass
        store.close()


def test_persist_turn_uses_atomic_add_turn():
    """写路径护栏：web_server 的持久化必须走 add_turn，不得退回非原子的三步调用。"""
    with open(os.path.join(ROOT, "web_server.py"), encoding="utf-8") as f:
        src = f.read()
    assert "store.add_turn(" in src, "web_server 未使用原子 add_turn——L1 的修复被回退"
    assert "store.add_message(" not in src, (
        "web_server 仍直接调用非原子的 add_message（一轮 = 两个事务），"
        "半回合风险回归"
    )
