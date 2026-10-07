#!/usr/bin/env python3
"""本机存储环境体检 — 五层分辨，每层给出可直接粘贴的修复命令。

背景（2026-10-07 存储加固 R1/X2/X3）：
setup.sh 原先只做 `command -v psql && pg_isready`，把「没装 / 装了没起 / 起了没建库 /
角色不存在」四种失败压成一句「未检测到可用 PostgreSQL」，且提示文案与真实降级链
（文件 store，重启不丢）矛盾。用户装完 PG 没有任何验证手段——装机变成一次盲测。
「装完忘启动、或重启后 brew services 没自启」是最高频的真实故障。

五层：
  L1 驱动      psycopg 能否导入（.venv 依赖是否完整）
  L2 服务      host:port 能否连上（区分"没装"与"装了没起"）
  L3 目标库    目标库是否存在（需建库权限）
  L4 连接可用  能否连上目标库 + 有 CREATE 权限（幂等建表需要）
  L5 表结构    tasks / messages 是否就绪（缺则说明服务启动时会自动建）

用法：
    .venv/bin/python3 scripts/doctor.py              # 人类可读报告
    .venv/bin/python3 scripts/doctor.py --json       # 机器可读（供 CI / setup.sh 消费）
    .venv/bin/python3 scripts/doctor.py --dsn postgresql://...   # 体检指定连接串

退出码：0 = 全绿；1 = 需要人工动作（报告里附命令）；2 = 用法/环境错误。

本脚本只读：不做任何建库建表（要建库请跑 scripts/init_db.py）。
"""

import argparse
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from storage import dburl  # noqa: E402
from storage.local_store import _pg_connect_params  # noqa: E402

# 体检用短超时：体检不该让用户等（失败预算是给生产路径的，这里只要 3s）
_PROBE_TIMEOUT_S = 3


def _admin_conn_params(dsn: str) -> dict:
    """探服务可用性用的连接参数：管住超时，不改用户 DSN。"""
    params = dict(_pg_connect_params(dsn))
    params.setdefault("connect_timeout", _PROBE_TIMEOUT_S)
    return params


def _install_hints() -> list:
    """按平台给出安装/启动命令（macOS 优先 brew，Linux 给 apt/dnf）。"""
    hints = []
    if sys.platform == "darwin" or shutil.which("brew"):
        hints.append("macOS : brew install postgresql@16 && brew services start postgresql@16")
    if shutil.which("apt"):
        hints.append("Debian/Ubuntu: sudo apt install postgresql && sudo systemctl start postgresql")
    if shutil.which("dnf") or shutil.which("yum"):
        hints.append("Fedora/RHEL  : sudo dnf install postgresql-server && sudo postgresql-setup --initdb")
    if not hints:
        hints.append("请按发行版安装 PostgreSQL 16+，并确保服务监听 5432")
    hints.append("不想装本机服务：export PGDATABASE_URL=postgresql://<user>@<host>:5432/<db>")
    return hints


def _pg_server_binaries_present() -> bool:
    """本机是否装了 PG 服务端/客户端（用于区分「没装」与「装了没起」）。"""
    if any(shutil.which(b) for b in ("psql", "pg_ctl", "pg_isready", "postgres")):
        return True
    for prefix in ("/opt/homebrew/opt", "/usr/local/opt", "/usr/lib/postgresql"):
        if os.path.isdir(prefix):
            for name in os.listdir(prefix):
                if name.startswith("postgresql"):
                    return True
    return False


def run_checks(dsn: str) -> dict:
    """跑五层检查，返回结构化结果（不打印、不退出）。"""
    layers = []
    host, port = dburl.host_port(dsn)
    dbname = dburl.dbname(dsn) or "?"

    # ── L1 驱动 ──────────────────────────────────────────────────────────
    psycopg = None
    try:
        import psycopg as _psycopg
        psycopg = _psycopg
        layers.append({
            "layer": "L1 驱动", "ok": True,
            "detail": f"psycopg {getattr(psycopg, '__version__', '?')} 已安装",
            "fix": [],
        })
    except Exception as e:  # noqa: BLE001
        layers.append({
            "layer": "L1 驱动", "ok": False,
            "detail": f"psycopg 导入失败：{e}",
            "fix": ["uv sync   # psycopg 在主依赖里，uv sync 即可恢复"],
        })
        return {"dsn_target": dburl.target(dsn), "layers": layers, "ok": False}

    # ── L2 服务可达 ──────────────────────────────────────────────────────
    admin_dsn = dburl.with_dbname(dsn, "postgres")
    try:
        with psycopg.connect(admin_dsn, autocommit=True, **_admin_conn_params(admin_dsn)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                ver = (cur.fetchone() or ["?"])[0]
        layers.append({"layer": "L2 服务", "ok": True,
                       "detail": f"{host}:{port} 可连 — {str(ver).split(',')[0]}", "fix": []})
    except Exception as e:  # noqa: BLE001
        if _pg_server_binaries_present():
            detail = f"{host}:{port} 连不上，但本机装了 PG——多半是服务没起"
            fix = ["macOS : brew services start postgresql@16",
                   "Linux : sudo systemctl start postgresql",
                   "查看状态: pg_isready    （或 brew services list）"]
        else:
            detail = f"{host}:{port} 连不上，且本机未发现 PG 可执行文件——多半是没装"
            fix = _install_hints()
        layers.append({"layer": "L2 服务", "ok": False,
                       "detail": f"{detail}（{dburl.mask_text(str(e))}）", "fix": fix})
        return {"dsn_target": dburl.target(dsn), "layers": layers, "ok": False}

    # ── L3 目标库存在 ────────────────────────────────────────────────────
    try:
        with psycopg.connect(admin_dsn, autocommit=True, **_admin_conn_params(admin_dsn)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
                exists = cur.fetchone() is not None
        if exists:
            layers.append({"layer": "L3 目标库", "ok": True, "detail": f"库 {dbname} 存在", "fix": []})
        else:
            layers.append({
                "layer": "L3 目标库", "ok": False,
                "detail": f"服务在跑，但库 {dbname} 不存在（store 会连不上它 → 降级文件 store）",
                "fix": [".venv/bin/python3 scripts/init_db.py   # 幂等建库建表"],
            })
            return {"dsn_target": dburl.target(dsn), "layers": layers, "ok": False}
    except Exception as e:  # noqa: BLE001
        layers.append({"layer": "L3 目标库", "ok": False,
                       "detail": f"查询库清单失败（角色权限？）：{dburl.mask_text(str(e))}",
                       "fix": [".venv/bin/python3 scripts/init_db.py",
                               "若角色不存在：createuser -s $(whoami)"] })
        return {"dsn_target": dburl.target(dsn), "layers": layers, "ok": False}

    # ── L4 目标库可用（连接 + 建表权限）──────────────────────────────────
    try:
        with psycopg.connect(dsn, autocommit=True, **_admin_conn_params(dsn)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT has_database_privilege(current_database(), 'CREATE'),"
                            " current_user")
                can_create, who = cur.fetchone()
        if can_create:
            layers.append({"layer": "L4 连接可用", "ok": True,
                           "detail": f"以 {who} 连上 {dbname}，且有 CREATE 权限", "fix": []})
        else:
            layers.append({
                "layer": "L4 连接可用", "ok": False,
                "detail": f"以 {who} 连上 {dbname}，但无 CREATE 权限——"
                          "服务首次连接时建表会失败并降级",
                "fix": [f'psql -d {dbname} -c "GRANT CREATE ON DATABASE {dbname} TO {who};"',
                        f'# 或用超级用户重建该库的属主：createdb -O {who} {dbname}'],
            })
            return {"dsn_target": dburl.target(dsn), "layers": layers, "ok": False}
    except Exception as e:  # noqa: BLE001
        layers.append({"layer": "L4 连接可用", "ok": False,
                       "detail": f"连接目标库失败：{dburl.mask_text(str(e))}",
                       "fix": _install_hints()})
        return {"dsn_target": dburl.target(dsn), "layers": layers, "ok": False}

    # ── L5 表结构 ────────────────────────────────────────────────────────
    try:
        with psycopg.connect(dsn, autocommit=True, **_admin_conn_params(dsn)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name IN ('tasks', 'messages')"
                )
                found = {r[0] for r in cur.fetchall()}
        missing = {"tasks", "messages"} - found
        if missing:
            layers.append({
                "layer": "L5 表结构", "ok": True,   # 不阻塞：服务启动会幂等建表
                "detail": f"缺少表 {sorted(missing)}——服务首次连接时会自动建（SCHEMA_SQL 幂等）",
                "fix": [".venv/bin/python3 scripts/init_db.py   # 想现在建就跑这个"],
            })
        else:
            layers.append({"layer": "L5 表结构", "ok": True, "detail": "tasks / messages 就绪", "fix": []})
    except Exception as e:  # noqa: BLE001
        layers.append({"layer": "L5 表结构", "ok": False,
                       "detail": f"表结构查询失败：{dburl.mask_text(str(e))}", "fix": []})

    return {"dsn_target": dburl.target(dsn), "layers": layers,
            "ok": all(l["ok"] for l in layers)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="本机存储环境体检（PostgreSQL）")
    ap.add_argument("--dsn", default=None, help="指定连接串（默认走 PGDATABASE_URL → config → 默认）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（供脚本消费）")
    args = ap.parse_args(argv)

    dsn = args.dsn or dburl.resolve_db_url()
    result = run_checks(dsn)
    result["dsn_safe"] = dburl.safe_url(dsn)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    print(f"[doctor] 目标：{result['dsn_target']}  （连接串：{result['dsn_safe']}）")
    for layer in result["layers"]:
        mark = "✅" if layer["ok"] else "❌"
        print(f"  {mark} {layer['layer']}：{layer['detail']}")
        for line in layer["fix"]:
            print(f"       → {line}")

    if result["ok"]:
        print("[doctor] 全绿：数据将落到上面的 PostgreSQL（PG 为持久化主档）。")
    else:
        print("[doctor] 有待处理项：按上面的 → 命令修复后重跑本脚本。")
        print("[doctor] 期间服务仍可用——会降级到 data/local_store.json（重启不丢），"
              "PG 恢复后用 scripts/migrate_json_to_pg.py 迁回。")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
