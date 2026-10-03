#!/usr/bin/env python3
"""清理历次测试遗留在真实数据库里的测试任务（M-00）。

背景：tests/ 长期直写真实 PG（无隔离，见 tests/conftest.py 落地前的历史），
任务表里积压了大量测试残留（"New task" / "xhr-task" / "测试任务" / probe-* 等），
污染真实任务列表。M-01 conftest 隔离落地后新残留不再产生，本脚本负责清历史存量。

用法（默认 dry-run，只列不动）：
    .venv/bin/python3 scripts/clean_test_tasks.py            # 预览将被清理的任务
    .venv/bin/python3 scripts/clean_test_tasks.py --apply    # 确认后软删（可恢复）

识别规则（保守，宁漏勿错）：
    1. 名称命中测试名模式（TEST_NAME_RE）；
    2. 同一秒内批量创建 >=3 个任务（测试批量写入的时间指纹），一并视为残留；
    3. 其余一律不动（真实任务如 "coffee" / "羊肉汤" 不会被碰）。

清理动作是软删（deleted_at 打点），走 store.delete_task()，与产品内删除一致，可恢复。
"""
import argparse
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from storage.local_store import get_store  # noqa: E402

# 测试写入用过的名字（tests/test_task_api.py 等）+ 探测脚本指纹
TEST_NAME_RE = re.compile(
    r"^(New task|xhr-task|测试任务|改口测试|冒烟任务|链路完整性探测|probe-.*|旧名|新名|T|删)$"
)
BATCH_THRESHOLD = 3  # 同秒创建 >=3 个即视为测试批量


def find_residue(tasks):
    """返回 [(task, reason), ...]，reason 说明命中哪条规则。"""
    by_second = defaultdict(list)
    for t in tasks:
        ts = str(t.get("created_at", ""))[:19]  # 精度到秒
        by_second[ts].append(t)

    residue = []
    for t in tasks:
        name = t.get("name", "")
        ts = str(t.get("created_at", ""))[:19]
        if TEST_NAME_RE.match(name or ""):
            residue.append((t, f"测试名模式: {name!r}"))
        elif len(by_second[ts]) >= BATCH_THRESHOLD:
            residue.append((t, f"同秒批量({len(by_second[ts])}个 @ {ts}): {name!r}"))
    # 去重（可能同时命中两条规则）
    seen, out = set(), []
    for t, reason in residue:
        if t["id"] not in seen:
            seen.add(t["id"])
            out.append((t, reason))
    return out


def main():
    ap = argparse.ArgumentParser(description="清理历次测试遗留在真实数据库里的测试任务（默认 dry-run）")
    ap.add_argument("--apply", action="store_true", help="真正软删（默认只预览）")
    args = ap.parse_args()

    store = get_store()
    tasks = store.list_tasks()
    residue = find_residue(tasks)

    print(f"存储后端: {type(store).__name__}")
    print(f"现有任务: {len(tasks)} 条，识别为测试残留: {len(residue)} 条")
    for t, reason in residue:
        print(f"  {str(t.get('created_at', '?'))[:19]}  {t['id']}  {reason}")

    if not args.apply:
        print("\n[dry-run] 未做任何修改。确认无误后加 --apply 执行软删。")
        return 0

    for t, _ in residue:
        store.delete_task(t["id"])
    print(f"\n已软删 {len(residue)} 条测试残留（deleted_at 打点，可恢复）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
