"""隐私资产护栏：含用户数据的落盘物必须被 git 忽略 + 属主独占权限。

背景（2026-10-07 PG 连接加固审查 T3）：
含用户数据的落盘物共 4 类——PG 库、`data/local_store.json`（降级落盘：任务名 /
参数快照 / 完整对话历史）、`backups/*`（pg_dump 全库快照）、`logs/*.log`。
当时 `.gitignore` 忽略了 `logs/` 与 `*.gz`（备份仅靠这条侥幸挡住），
但 **`data/` 与 `backups/` 都没有显式条目**；LocalFileStore 又以默认 umask
（644）落盘。一次 `git add -A` 就可能把用户经营数据带进提交。

护栏三条：
1. `.gitignore` 必须显式忽略 `data/` 与 `backups/`——不依赖 `*.gz` 之类巧合；
2. LocalFileStore 落盘文件权限必须为 0600；
3. 历史遗留的宽松权限文件（644）在下次实例化时被收紧。
"""

import json
import os
import stat
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from storage.local_store import LocalFileStore  # noqa: E402


def _gitignore_lines():
    with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
        return [ln.strip() for ln in f]


@pytest.mark.parametrize("pattern", ["data/", "backups/"])
def test_user_data_dirs_are_gitignored(pattern):
    """用户数据落盘目录必须显式忽略。

    `data/` = LocalFileStore 降级落盘；`backups/` = pg_dump 全库快照。
    两者都含用户经营数据，缺失条目 = 隐私泄漏的唯一防线只剩"记得别 add"。
    """
    assert pattern in _gitignore_lines(), (
        f".gitignore 缺少 {pattern!r} 条目——该目录含用户经营数据与对话历史，"
        "一次 `git add -A` 就会入库。"
    )


def test_local_store_file_is_owner_only(tmp_path):
    """LocalFileStore 落盘文件必须是 0600（同机其他账户不可读）。"""
    p = tmp_path / "local_store.json"
    store = LocalFileStore(path=str(p))
    store.create_task("牛肉面店")

    assert p.is_file(), "LocalFileStore 未落盘——本护栏失去意义"
    mode = stat.S_IMODE(os.stat(p).st_mode)
    assert mode == 0o600, f"store 文件权限应为 600，实际 {oct(mode)}"


def test_local_store_tightens_legacy_permissive_file(tmp_path):
    """历史遗留的 644 文件（旧版本以默认 umask 落盘）在下次启动时被收紧。"""
    p = tmp_path / "local_store.json"
    p.write_text(json.dumps({"tasks": {}, "msgs": {}}), encoding="utf-8")
    os.chmod(p, 0o644)

    LocalFileStore(path=str(p))

    mode = stat.S_IMODE(os.stat(p).st_mode)
    assert mode == 0o600, f"历史 644 文件未被收紧，实际 {oct(mode)}"
