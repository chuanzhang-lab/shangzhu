"""存储加固收口（2026-10-08）：两件套的锁定测试。

A 备份新鲜度：防丢链条上唯一没有的一环——「有能力备份」≠「不会忘记备份」。
   没有新鲜度出口时，`make backup` 全靠人记得跑；忘了跑，前面 4 轮加固出的
   「可验证恢复」等于没发生。故必须有程序可读的出口（/health + doctor）。
B tasks.turn 死列：add_turn 只写 messages.turn，从不 UPDATE tasks.turn，
   导致 650 行全部恒为 0——任何读该列的代码拿到的都是错值。

定级：A/B 均为 P2（不阻塞运行，但分别是真·防丢缺口与数据不一致）。
红灯 → 绿灯：本文件在修复前必须 FAIL（backup_status 不存在 + turn 恒 0）。
"""
import os
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in __import__("sys").path:
    __import__("sys").path.insert(0, ROOT)
SRC = os.path.join(ROOT, "src")
if SRC not in __import__("sys").path:
    __import__("sys").path.insert(0, SRC)

from storage.local_store import LocalFileStore  # noqa: E402


# ── B：tasks.turn 必须随 add_turn 推进 ──────────────────────────────────
def test_add_turn_advances_task_turn(tmp_path):
    """add_turn 后任务的 turn 必须递增（此前恒为 0 —— 死列）。"""
    store = LocalFileStore(path=str(tmp_path / "store.json"))
    task = store.create_task(name="turn-检查")

    assert task["turn"] == 0, "新建任务 turn 应为 0"

    store.add_turn(task["id"], "月租金8000", "已记录", params={"monthly_rent": 8000}, turn=1)
    t1 = store.get_task(task["id"])
    assert t1["turn"] == 1, f"第 1 轮后 tasks.turn 应为 1，实际 {t1['turn']}"

    store.add_turn(task["id"], "员工3人", "已记录", params={"employee_count": 3}, turn=2)
    t2 = store.get_task(task["id"])
    assert t2["turn"] == 2, f"第 2 轮后 tasks.turn 应为 2，实际 {t2['turn']}"


def test_add_turn_turn_never_regresses(tmp_path):
    """乱序/旧回合重放时 turn 不得回退（取 max，不是覆盖）。"""
    store = LocalFileStore(path=str(tmp_path / "store.json"))
    task = store.create_task(name="turn-单调")
    store.add_turn(task["id"], "a", "b", params={}, turn=3)
    store.add_turn(task["id"], "c", "d", params={}, turn=1)  # 旧回合重放
    assert store.get_task(task["id"])["turn"] == 3, "turn 必须单调不回退"


# ── B2：tasks.industry 从 params 落库（同类死列）───────────────────────
def test_add_turn_sets_industry_from_params(tmp_path):
    """params 里带了行业 → tasks.industry 必须落库（此前 651 行全 NULL）。"""
    store = LocalFileStore(path=str(tmp_path / "store.json"))
    task = store.create_task(name="industry-检查")
    assert task["industry"] is None

    store.add_turn(task["id"], "开牛肉面店", "已记录",
                   params={"industry": "餐饮", "monthly_rent": 8000}, turn=1)
    assert store.get_task(task["id"])["industry"] == "餐饮"


def test_update_params_sets_industry(tmp_path):
    """update_params 路径同样要同步 industry。"""
    store = LocalFileStore(path=str(tmp_path / "store.json"))
    task = store.create_task(name="industry-update")
    store.update_params(task["id"], {"industry": "零售", "monthly_rent": 3000})
    assert store.get_task(task["id"])["industry"] == "零售"


def test_industry_not_clobbered_by_params_without_it(tmp_path):
    """params 没带 industry 时，已有值不得被清空（只增不抹）。"""
    store = LocalFileStore(path=str(tmp_path / "store.json"))
    task = store.create_task(name="industry-keep")
    store.add_turn(task["id"], "a", "b", params={"industry": "餐饮"}, turn=1)
    store.add_turn(task["id"], "c", "d", params={"monthly_rent": 9000}, turn=2)
    assert store.get_task(task["id"])["industry"] == "餐饮", "无 industry 的回合不得抹掉已定值"


# ── A：备份新鲜度 ────────────────────────────────────────────────────────
def test_backup_status_no_backup_is_stale(tmp_path):
    """一份备份都没有 → 明确 stale（这是最危险的防丢状态）。"""
    from storage import backup_status

    st = backup_status.backup_status(backup_dir=str(tmp_path / "nonexistent"))
    assert st["has_backup"] is False
    assert st["stale"] is True, "零备份必须判为 stale——否则用户会以为有兜底"
    assert st["age_days"] is None


def test_backup_status_fresh_backup_not_stale(tmp_path):
    """刚备份完 → 不 stale。"""
    from storage import backup_status

    d = tmp_path / "backups"
    d.mkdir()
    f = d / "shangzhu_20261008_000000.dump"
    f.write_bytes(b"PGDMP")
    st = backup_status.backup_status(backup_dir=str(d))
    assert st["has_backup"] is True
    assert st["age_days"] == 0
    assert st["stale"] is False
    assert st["latest"].endswith(".dump")


def test_backup_status_old_backup_is_stale(tmp_path):
    """超过阈值（默认 7 天）→ stale，并给出天数。"""
    from storage import backup_status

    d = tmp_path / "backups"
    d.mkdir()
    f = d / "old.dump"
    f.write_bytes(b"PGDMP")
    old = time.time() - 30 * 86400
    os.utime(f, (old, old))

    st = backup_status.backup_status(backup_dir=str(d), max_age_days=7)
    assert st["has_backup"] is True
    assert st["age_days"] >= 29
    assert st["stale"] is True
