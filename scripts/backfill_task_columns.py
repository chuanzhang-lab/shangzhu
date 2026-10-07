#!/usr/bin/env python3
"""回填 tasks 的派生列（turn / industry）—— 一次性数据修复（幂等，可重复执行）。

背景（2026-10-08 死列治理）：tasks 表有两列自建立以来从未被写过，
修代码只修了**增量**，存量仍是空值，读这些列的代码拿到的是错值：

- `turn`     ：实测 650 行恒为 0（回合数其实一直在 messages.turn 里）→ 已回填 131 行
- `industry` ：实测 651 行全 NULL（行业其实一直在 params JSON 里）→ 本脚本回填

回填规则：
    turn     = (SELECT MAX(turn) FROM messages WHERE task_id = tasks.id)
    industry = params->>'industry'   （只填 NULL，已有值不动）

幂等性：第二次跑时值已相等，影响行数为 0，可安全重复执行。
安全性：只 UPDATE 这两列，不动 params / messages / deleted_at / name。

用法：
    .venv/bin/python3 scripts/backfill_task_columns.py            # 预演（默认 dry-run）
    .venv/bin/python3 scripts/backfill_task_columns.py --apply    # 真正写入
    .venv/bin/python3 scripts/backfill_task_columns.py --json     # 机器可读

⚠️ 改数据前先备份：make backup
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from storage import dburl  # noqa: E402

_DRY_TURN_SQL = """
SELECT count(*) FROM tasks t
WHERE COALESCE(t.turn, 0) <> COALESCE(
    (SELECT MAX(m.turn) FROM messages m WHERE m.task_id = t.id), 0)
"""

_APPLY_TURN_SQL = """
UPDATE tasks t
SET turn = COALESCE((SELECT MAX(m.turn) FROM messages m WHERE m.task_id = t.id), 0)
WHERE COALESCE(t.turn, 0) <> COALESCE(
    (SELECT MAX(m.turn) FROM messages m WHERE m.task_id = t.id), 0)
"""

# industry：只填空着的（已有值不动 —— 与代码侧「只增不抹」语义一致）
_DRY_INDUSTRY_SQL = """
SELECT count(*) FROM tasks
WHERE industry IS NULL AND params ? 'industry'
      AND COALESCE(params->>'industry', '') <> ''
"""

_APPLY_INDUSTRY_SQL = """
UPDATE tasks
SET industry = params->>'industry'
WHERE industry IS NULL AND params ? 'industry'
      AND COALESCE(params->>'industry', '') <> ''
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
                cur.execute(_DRY_TURN_SQL)
                pending_turn = cur.fetchone()[0]
                cur.execute(_DRY_INDUSTRY_SQL)
                pending_industry = cur.fetchone()[0]

                updated_turn = updated_industry = 0
                if args.apply:
                    cur.execute(_APPLY_TURN_SQL)
                    updated_turn = cur.rowcount or 0
                    cur.execute(_APPLY_INDUSTRY_SQL)
                    updated_industry = cur.rowcount or 0
                    conn.commit()

                cur.execute("SELECT count(*), COALESCE(SUM(turn),0) FROM tasks")
                total, turn_sum = cur.fetchone()
                cur.execute("SELECT count(*) FROM tasks WHERE industry IS NOT NULL")
                industry_filled = cur.fetchone()[0]
    except Exception as e:  # noqa: BLE001
        print(f"[backfill] 失败：{dburl.mask_text(str(e))}", file=sys.stderr)
        return 2

    out = {
        "target": dburl.target(dsn),
        "turn_pending_before": pending_turn,
        "turn_updated": updated_turn,
        "industry_pending_before": pending_industry,
        "industry_updated": updated_industry,
        "tasks_total": total,
        "turn_sum_after": turn_sum,
        "industry_filled_after": industry_filled,
        "applied": args.apply,
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(f"[backfill] 目标：{out['target']}")
    print(f"[backfill] turn     待对齐 {pending_turn} 行")
    print(f"[backfill] industry 待补齐 {pending_industry} 行")
    if args.apply:
        print(f"[backfill] 已更新：turn {updated_turn} 行、industry {updated_industry} 行"
              "（幂等：再跑应为 0 / 0）")
    else:
        print("[backfill] 预演模式（未写入）——加 --apply 才真正修改")
    print(f"[backfill] 任务总数 {total}，turn 合计 {turn_sum}，"
          f"industry 非空 {industry_filled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
