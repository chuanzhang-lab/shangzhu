"""备份新鲜度 — 把「防丢」从「有能力备份」推进到「不会忘记备份」。

背景（2026-10-08 收口 A）：前 4 轮加固把备份本身做得很扎实——`-Fc` 产物、
写完即 `pg_restore --list` 校验、`restore_db.sh` 四档、`make drill` 演练。
但**没有任何一处告诉用户"你多久没备份了"**：`make backup` 全靠人记得跑。
人忘了跑，再好的可恢复性也等于没发生——这是防丢链条上唯一还开着的一环。

本模块只做一件事：回答「最新一份备份在哪、多久前的、算不算过期」，
并给出一个程序可读的出口（`/health` 字段 + `doctor.py` 一层），
让"该备份了"能被看见，而不是靠记忆。

设计约束：
- **只读**：不触发备份、不写文件（触发备份是 backup_db.sh 的职责）。
- **不绑定库**：只看 backups/ 下的 `.dump` 文件 mtime。跨库备份混放时
  只按 mtime 取最新——够用，且不会因为解析文件名而误判。
- 阈值可配：`BACKUP_MAX_AGE_DAYS`（默认 7，与 backup_db.sh 保留 7 份对齐）。

用法：
    .venv/bin/python3 src/storage/backup_status.py            # 人类可读
    .venv/bin/python3 src/storage/backup_status.py --json     # 机器可读
"""

from __future__ import annotations

import glob
import json
import os
import sys
import time

# 仓库根：backups/ 的定位基准（本文件在 src/storage/ 下）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_BACKUP_DIR = os.path.join(_PROJECT_ROOT, "backups")
DEFAULT_MAX_AGE_DAYS = 7


def _max_age_days() -> int:
    raw = (os.getenv("BACKUP_MAX_AGE_DAYS") or "").strip()
    if not raw:
        return DEFAULT_MAX_AGE_DAYS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_AGE_DAYS


def latest_backup(backup_dir: str = DEFAULT_BACKUP_DIR) -> dict:
    """最新一份备份：路径 / mtime / 距今天数。没有则返回 has_backup=False。"""
    if not os.path.isdir(backup_dir):
        return {"has_backup": False, "latest": None, "mtime": None, "age_days": None}

    candidates = [p for p in glob.glob(os.path.join(backup_dir, "*.dump"))
                  if os.path.isfile(p)]
    # 兼容早期 .sql.gz 产物（backup_db.sh 改 -Fc 之前的历史备份）
    candidates += [p for p in glob.glob(os.path.join(backup_dir, "*.sql.gz"))
                   if os.path.isfile(p)]
    if not candidates:
        return {"has_backup": False, "latest": None, "mtime": None, "age_days": None}

    newest = max(candidates, key=os.path.getmtime)
    mtime = os.path.getmtime(newest)
    age_days = int((time.time() - mtime) // 86400)
    return {
        "has_backup": True,
        "latest": os.path.basename(newest),
        "latest_path": newest,
        "mtime": mtime,
        "age_days": age_days,
    }


def backup_status(backup_dir: str = DEFAULT_BACKUP_DIR,
                  max_age_days: int | None = None) -> dict:
    """完整新鲜度视图（供 /health 与 doctor 消费）。

    stale 语义（宁可多报，不可漏报）：
      - 零备份          → stale（最危险：以为有兜底其实没有）
      - 超过阈值        → stale
      - 否则            → 不 stale
    """
    limit = _max_age_days() if max_age_days is None else max_age_days
    info = latest_backup(backup_dir)
    has = info["has_backup"]
    age = info["age_days"]
    stale = (not has) or (age is not None and age > limit)

    reason = None
    if not has:
        reason = f"backups/ 下没有备份产物（{backup_dir}）——现在还没有任何可恢复点"
    elif age is not None and age > limit:
        reason = f"最新备份已 {age} 天前（阈值 {limit} 天）——该跑了：make backup"

    return {
        "has_backup": has,
        "latest": info["latest"],
        "age_days": age,
        "max_age_days": limit,
        "stale": stale,
        "reason": reason,
        "backup_dir": backup_dir,
    }


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    st = backup_status(DEFAULT_BACKUP_DIR)
    if "--json" in args:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 1 if st["stale"] else 0

    if not st["has_backup"]:
        print(f"[backup-status] ❌ 没有任何备份 —— 立即跑一次：make backup", )
        print(f"[backup-status]    备份目录：{st['backup_dir']}")
        return 1
    mark = "❌" if st["stale"] else "✅"
    print(f"[backup-status] {mark} 最新备份 {st['latest']}（{st['age_days']} 天前，"
          f"阈值 {st['max_age_days']} 天）")
    if st["stale"]:
        print(f"[backup-status]    → make backup")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
