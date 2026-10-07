#!/usr/bin/env python3
"""回填 tasks.turn —— 一次性数据修复（幂等，可重复执行）。

背景（2026-10-08 加固 B）：`tasks.turn` 列自建立以来从未被写过，实测 650 行
全部恒为 0（死列），而真实回合数只存在于 `messages.turn`。修代码（add_turn 现在
会推进 turn）只修了**增量**，存量仍是 0，读该列的代码依旧拿到错值。

本脚本把存量对齐到「该任务已有消息的最大 turn」：
    UPDATE tasks SET turn = (SELECT MAX(turn) FROM messages WHERE task_id = tasks.id)

幂等性：第二次跑时值已相等，影响行数为 0，可安全重复执行。
安全性：只 UPDATE turn 一列，不动 params / messages / deleted_at。

用法：
    .venv/bin/python3 scripts/backfill_task_turn.py            # 预演（默认 dry-run）
    .venv/bin/python3 scripts/backfill_task_turn.py --apply    # 真正写入
    .venv/bin/python3 scripts/backfill_task_turn.py --json     # 机器可读

⚠️ 改数据前先备份：make backup
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from storage import dburl  # noqa: E402

_DRY_SQL = """
SELECT count(*) FROM tasks t
WHERE COALESCE(t.turn, 0) <> COALESCE(
    (SELECT MAX(m.turn) FROM messages m WHERE m.task_id = t.id), 0)
"""

_APPLY_SQL = """
UPDATE tasks t
SET turn = COALESCE((SELECT MAX(m.turn) FROM messages m WHERE m.task_id = t.id), 0)
WHERE COALESCE(t.turn, 0) <> COALESCE(
    (SELECT MAX(m.turn) FROM messages m WHERE m.task_id = t.id), 0)
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="回填 tasks.turn（幂等）")
    ap.add_argument("--apply", action="store_true", help="真正写入（默认只预演）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    dsn = dburl.resolve_db_url()
    try:
        import psycopg
    except Exception as e:  # noqa: BLE001
        print(f"[backfill] psycopg 不可用：{e}", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(dsn, autocommit=not args.apply) as conn:
            with conn.cursor() as cur:
                cur.execute(_DRY_SQL)
                pending = cur.fetchone()[0]
                if args.apply:
                    cur.execute(_APPLY_SQL)
                    updated = cur.rowcount or 0
                    conn.commit()
                else:
                    updated = 0
                cur.execute("SELECT count(*), COALESCE(SUM(turn),0) FROM tasks")
                total, turn_sum = cur.fetchone()
    except Exception as e:  # noqa: BLE001
        print(f"[backfill] 失败：{dburl.mask_text(str(e))}", file=sys.stderr)
        return 2

    out = {
        "target": dburl.target(dsn),
        "pending_before": pending,
        "updated": updated,
        "tasks_total": total,
        "turn_sum_after": turn_sum,
        "applied": args.apply,
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(f"[backfill] 目标：{out['target']}")
    print(f"[backfill] 待对齐任务数：{pending}")
    if args.apply:
        print(f"[backfill] 已更新：{updated} 行（幂等：再跑应为 0）")
    else:
        print("[backfill] 预演模式（未写入）——加 --apply 才真正修改")
    print(f"[backfill] 任务总数 {total}，turn 合计 {turn_sum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
