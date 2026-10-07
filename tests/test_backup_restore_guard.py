"""备份/恢复护栏：备份必须可校验、恢复必须存在且演练过。

背景（2026-10-07 存储加固审查 X1，P0）：
此前只有 `backup_db.sh`（pg_dump | gzip），**没有恢复脚本、没有恢复步骤文档、产物
从不校验**；且它自己拼 `$(whoami)` + 写死库名，用户改过 PGDATABASE_URL 后备份的
可能是另一个库（L4）。「备份过」于是只是纸面承诺——真出事时没演练过、没验证过。

护栏五条：
1. 备份脚本必须从 dburl 单源取连接串/库名（不得再写死 whoami / shangzhu）；
2. 备份必须是 -Fc 且**写完即校验**（pg_restore --list 能列目录）；
3. 备份产物 600、backups/ 700（含用户数据）；
4. 恢复脚本必须存在、可执行，且提供 --check / --into-db / --rehearsal / --force 四档；
5. 恢复后行数核对逻辑存在（演练 = 可证伪）；--force 必须有人工确认闸。
"""

import os
import subprocess
import sys
import stat

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP = os.path.join(ROOT, "scripts", "backup_db.sh")
RESTORE = os.path.join(ROOT, "scripts", "restore_db.sh")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _code_only(src):
    """剥掉整行注释与行尾注释：护栏要抓的是代码行为，不是历史说明里的字样。"""
    lines = []
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        lines.append(line.split(" #", 1)[0])
    return "\n".join(lines)


def test_backup_uses_single_source_dburl():
    """备份的连接串与库名必须来自 dburl 单源：写死 whoami/库名 = 可能备份错库（L4）。"""
    src = _read(BACKUP)
    code = _code_only(src)
    assert "dburl.py" in code, "backup_db.sh 未使用 storage/dburl.py 单源"
    assert "--dbname" in code and "--target" in code
    assert "whoami" not in code, (
        "backup_db.sh 又自己拼 whoami 了——库名/用户名会与实际 store 不一致（L4 复发）"
    )
    # 连接串必须原样交给 pg_dump（而不是重新拼一个 localhost:5432/<写死的库>）
    assert 'pg_dump --format=custom --dbname="$URL"' in code


def test_backup_verifies_artifact_and_permissions():
    """-Fc + 写完即校验 + 0600：备份必须"可验证"而非"看起来生成了"。"""
    src = _read(BACKUP)
    assert "--format=custom" in src or " -Fc" in src, "未用自定义格式——无法 pg_restore --list 校验"
    assert "pg_restore --list" in src, "备份后未校验产物（X1：不可验证的备份不算备份）"
    assert "chmod 600" in src, "备份产物未收紧权限（含全库用户数据）"
    assert "chmod 700" in src, "backups/ 目录未收紧权限"


def test_restore_script_exists_and_is_executable():
    """恢复脚本必须存在且可执行：没有恢复路径的备份是纸面承诺（X1）。"""
    assert os.path.isfile(RESTORE), "缺少 scripts/restore_db.sh——只有备份没有恢复"
    mode = stat.S_IMODE(os.stat(RESTORE).st_mode)
    assert mode & stat.S_IXUSR, f"restore_db.sh 不可执行（{oct(mode)}）"
    mode_b = stat.S_IMODE(os.stat(BACKUP).st_mode)
    assert mode_b & stat.S_IXUSR, f"backup_db.sh 不可执行（{oct(mode_b)}）"


def test_restore_offers_check_rehearsal_and_confirmation_gate():
    """恢复脚本四档齐备，且 --force 必须有人工确认闸（覆盖生产库是危险动作）。"""
    src = _read(RESTORE)
    for flag in ("--check", "--into-db", "--rehearsal", "--force"):
        assert flag in src, f"restore_db.sh 缺少 {flag} 档"
    assert "pg_restore --list" in src, "恢复前未先校验产物"
    assert "read -r answer" in src and '[ "$answer" = "yes" ]' in src, (
        "--force 缺少人工确认闸——覆盖生产库必须交互确认"
    )
    assert "--no-owner" in src, "恢复未加 --no-owner（跨机器/跨用户名的备份会因属主不存在失败）"
    assert "verify_counts" in src, "恢复后无行数核对——演练不可证伪"


def test_backup_check_runs_on_real_artifact():
    """若 backups/ 下已有真实产物，--check 必须通过（对真实文件而非 mock 校验）。

    CI/新克隆环境没有产物时跳过——此时上面的静态护栏仍然生效。
    """
    backup_dir = os.path.join(ROOT, "backups")
    if not os.path.isdir(backup_dir):
        pytest.skip("尚无 backups/ 目录（未跑过备份）")
    dumps = [f for f in os.listdir(backup_dir) if f.endswith(".dump")]
    if not dumps:
        pytest.skip("backups/ 下暂无 .dump 产物")
    if not all(shutil_which(t) for t in ("pg_restore", "psql")):
        pytest.skip("本机无 pg_restore/psql 客户端")

    proc = subprocess.run(
        ["bash", RESTORE, "--check", "--file", os.path.join(backup_dir, sorted(dumps)[-1])],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "PY": sys.executable},
    )
    assert proc.returncode == 0, f"--check 未通过：stdout={proc.stdout} stderr={proc.stderr}"
    assert "校验通过" in proc.stdout


def shutil_which(name):
    from shutil import which

    return which(name)
