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


# ── 密钥迁移脚本（P-1 隐私收口）：读回校验 + 不擅自删用户文件 ────────────────

def _load_migrate_module():
    """按路径加载迁移脚本（它不在包内，scripts/ 下独立运行）。"""
    import importlib.util

    path = os.path.join(ROOT, "scripts", "migrate_key_to_keyring.py")
    spec = importlib.util.spec_from_file_location("_migrate_key_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_key_migration_verifies_readback_and_needs_flag_to_delete():
    """两条硬规则：迁移必须读回校验（否则会静默丢密钥）；删历史副本必须有显式开关。"""
    with open(os.path.join(ROOT, "scripts", "migrate_key_to_keyring.py"), encoding="utf-8") as f:
        src = f.read()
    assert "_keychain_read()" in src and "readback != current_key" in src, (
        "迁移脚本缺少读回校验——写失败时会把 config 里的明文清掉，密钥静默丢失"
    )
    assert "--clean-bak" in src, "缺少显式删除开关：不许默认删除用户文件"


def test_key_migration_reports_but_keeps_bak_by_default(tmp_path, monkeypatch):
    """默认只报告不明文副本、不删除；加 --clean-bak 才删。"""
    mod = _load_migrate_module()

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    main_cfg = config_dir / "agent_llm_config.json"
    bak_cfg = config_dir / "agent_llm_config.json.bak"
    # 主文件已迁移（无 api_key），历史副本仍带明文密钥
    main_cfg.write_text(json.dumps({"config": {"model": "m"}}), encoding="utf-8")
    bak_cfg.write_text(json.dumps({"config": {"model": "m", "api_key": "sk-LEAKED-EXAMPLE"}}),
                       encoding="utf-8")

    monkeypatch.setattr(mod, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(mod, "CONFIG_FILE", str(main_cfg))

    assert mod.main([]) == 0
    assert bak_cfg.exists(), "默认竟然删除了用户的历史副本文件（应由 --clean-bak 显式触发）"

    assert mod.main(["--clean-bak"]) == 0
    assert not bak_cfg.exists(), "--clean-bak 未删除含明文密钥的历史副本"

