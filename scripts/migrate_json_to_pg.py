#!/usr/bin/env python3
"""孤儿数据迁移：降级期写进本地 JSON 的任务搬回 PostgreSQL（M-10 附带治理）。

背景：get_store() 降级链 PG → LocalFileStore → Memory。若某次启动 PG 恰好没起，
任务写进 JSON 文件；PG 恢复后 get_store() 切回 PG，那批 JSON 数据**不会自动迁移**
（孤儿数据）。get_store() 的 WARNING 已提示运行本脚本。

用法（默认 dry-run，只预览不动）：
    .venv/bin/python3 scripts/migrate_json_to_pg.py             # 预览将迁移的任务
    .venv/bin/python3 scripts/migrate_json_to_pg.py --apply    # 执行迁移

迁移口径：
- 逐条 create_task + add_message + update_params 走 PG store 接口；
- **幂等**：双闸去重——① 已迁移过的源任务 id 记入 sidecar 文件
  `<源文件>.migrated_ids`，重复运行直接跳过；② PG 中已存在同名同参数任务也跳过
  （覆盖 sidecar 丢失的场景）。created_at 不可保真（PG store 接口不支持自定义
  时间戳，迁移任务以迁移时刻计）；
- 源 JSON 文件迁移后不删除（备份留底），确认 PG 无误后手动归档；
- PG 不可用时直接报错退出——绝不把数据搬去另一个降级点。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from storage.local_store import LocalFileStore, PostgresStore, _file_store_path  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="降级期 JSON 孤儿数据迁移回 PostgreSQL")
    ap.add_argument("--apply", action="store_true", help="真正迁移（默认 dry-run）")
    ap.add_argument("--json-path", default=None, help="指定源 JSON 文件（默认 LOCAL_STORE_PATH/内置路径）")
    args = ap.parse_args()

    src_path = args.json_path or _file_store_path()
    if not os.path.isfile(src_path):
        print(f"源 JSON 文件不存在：{src_path}，无孤儿数据可迁")
        return 0

    src = LocalFileStore(path=src_path)
    tasks = src.list_tasks()
    if not tasks:
        print(f"{src_path} 中无任务，无需迁移")
        return 0

    try:
        pg = PostgresStore()
        pg.ping()
    except Exception as e:  # noqa: BLE001
        print(f"PostgreSQL 不可用（{e}）——拒绝迁移（不把数据搬去另一个降级点）", file=sys.stderr)
        return 1

    existing_names_params = {
        (t.get("name"), json.dumps(t.get("params") or {}, sort_keys=True, ensure_ascii=False))
        for t in pg.list_tasks()
    }
    sidecar = f"{src_path}.migrated_ids"
    done_ids = set()
    if os.path.isfile(sidecar):
        try:
            with open(sidecar, encoding="utf-8") as f:
                done_ids = set(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass

    def _sig(t):
        return (t.get("name"), json.dumps(t.get("params") or {}, sort_keys=True, ensure_ascii=False))

    to_move = [t for t in tasks
               if t["id"] not in done_ids and _sig(t) not in existing_names_params]
    skipped = len(tasks) - len(to_move)

    print(f"源: {src_path}（{len(tasks)} 条）→ PostgreSQL（已迁移/已存在跳过 {skipped} 条，待迁移 {len(to_move)} 条）")
    for t in to_move:
        print(f"  {t.get('id')}  {t.get('name', '?')!r}  msgs={len(src.get_messages(t['id']))}")

    if not args.apply:
        print("\n[dry-run] 未做任何修改。确认后加 --apply 执行。")
        return 0

    moved = 0
    for t in to_move:
        nt = pg.create_task(t.get("name", "迁移任务"))
        if t.get("params"):
            pg.update_params(nt["id"], t["params"])
        for m in src.get_messages(t["id"]):
            pg.add_message(nt["id"], m.get("role", "user"), m.get("content", ""), m.get("turn", 0))
        done_ids.add(t["id"])
        moved += 1
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(sorted(done_ids), f)
    print(f"\n已迁移 {moved} 条任务（含消息历史）。源文件保留作备份：{src_path}")
    print(f"已迁移 id 台账：{sidecar}（重复运行不会再迁）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
