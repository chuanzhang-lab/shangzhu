"""数据库连接串的唯一出处（single source of truth）。

优先级（与 README 口径一致）：`PGDATABASE_URL` → `config/storage.json` 的 `db_url`
→ 内置默认（本机系统用户名免密 peer 连接）。

背景（2026-10-07 存储加固 L4）：此前 URL 解析散在三处——`local_store._db_url()`
（三级优先）、`scripts/init_db.py` 的 `DEFAULT_*`、`scripts/backup_db.sh` 的
`PGUSER:-whoami` + 写死库名。后果很具体：用户用 `PGDATABASE_URL` 指向自定义库后，
备份脚本备份的是**另一个库**（或直接失败）——「备份过」和「备份的是你用的库」是两件事。

作为 CLI 使用（供 shell 脚本 / 体检脚本复用，避免出现第四份解析）：

    .venv/bin/python3 src/storage/dburl.py            # 完整连接串（含凭据，谨慎）
    .venv/bin/python3 src/storage/dburl.py --safe     # 脱敏串（密码/用户名 → ***）
    .venv/bin/python3 src/storage/dburl.py --target   # host:port/dbname（无凭据）
    .venv/bin/python3 src/storage/dburl.py --dbname   # 仅库名
    .venv/bin/python3 src/storage/dburl.py --host     # 仅主机（配 --port 用）
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys

# 免密本地连接默认用当前系统用户名（peer auth），不绑定某台机器。
DEFAULT_DB_URL = f"postgresql://{getpass.getuser()}@localhost:5432/shangzhu"

# 仓库根：config/storage.json 与默认库名的定位基准（本文件在 src/storage/ 下）。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_KV_RE = re.compile(r"(\w+)\s*=\s*([^\s]+)")
# 连接串里的 user:password@（日志/错误信息脱敏用）
_CRED_RE = re.compile(r"://([^:/@\s]+):([^@\s]+)@")


def resolve_db_url() -> str:
    """业务库连接串，三级优先级：env var → config file → 内置默认。"""
    env_url = os.getenv("PGDATABASE_URL")
    if env_url and env_url.strip():
        return env_url.strip()

    config_path = os.path.join(_PROJECT_ROOT, "config", "storage.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        file_url = (cfg.get("db_url") or "").strip()
        if file_url:
            return file_url
    except (OSError, json.JSONDecodeError):
        pass

    return DEFAULT_DB_URL


# store 档位（2026-10-07 加固 S3：把「选择权」补回来）
#   auto   ← 默认，降级链 PG → 文件 → 内存（行为与本变量出现前完全一致）
#   pg     ← 只许 PG：连不上就明确报错，**不降级**（要"要么 PG 要么告诉我"的用户用这档）
#   file   ← 显式跳过 PG，任务直接落 data/local_store.json（重启不丢，不与 PG 同步）
#   memory ← 显式选择内存（数据重启即丢，仅供演示/测试）
STORE_BACKENDS = ("auto", "pg", "file", "memory")


def resolve_store_backend() -> str:
    """store 档位：env STORE_BACKEND → config/storage.json 的 backend → auto。

    非法档位名直接 ValueError（早失败）：拼错档位若静默退回 auto，用户会以为
    自己锁死了 PG，实际却在悄悄降级——正是本变量要消除的那种不确定性。
    """
    raw = (os.getenv("STORE_BACKEND") or "").strip().lower()
    if not raw:
        config_path = os.path.join(_PROJECT_ROOT, "config", "storage.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            raw = str(cfg.get("backend") or "").strip().lower()
        except (OSError, json.JSONDecodeError):
            raw = ""
    if not raw:
        return "auto"
    if raw not in STORE_BACKENDS:
        raise ValueError(
            f"未知 store 档位 {raw!r}——允许值：{', '.join(STORE_BACKENDS)}"
            "（可用 env STORE_BACKEND 或 config/storage.json 的 backend 字段设置）"
        )
    return raw


def _parts(url: str) -> dict:
    """解析 URI 或 keyword=value 形式（best-effort），返回各字段字符串。

    只用于展示与定位，不参与连接——连接串原样交给 libpq，避免自造解析器成为
    新的错误来源。
    """
    if "://" in url:
        from urllib.parse import unquote, urlsplit

        u = urlsplit(url)
        try:
            port = u.port or ""
        except ValueError:
            port = ""
        return {
            "host": u.hostname or "",
            "port": str(port),
            "dbname": (u.path or "").lstrip("/"),
            "user": unquote(u.username or ""),
            "password": unquote(u.password or ""),
        }
    return {k: v.strip("'\"") for k, v in _KV_RE.findall(url)}


def safe_url(url: str) -> str:
    """脱敏连接串：用户名与密码替换为 ***（用于日志与展示）。"""
    if "://" in url:
        from urllib.parse import urlsplit, urlunsplit

        u = urlsplit(url)
        host = u.hostname or ""
        if ":" in host:  # IPv6
            host = f"[{host}]"
        netloc = f"***:***@{host}" if (u.username or u.password) else host
        try:
            if u.port:
                netloc += f":{u.port}"
        except ValueError:
            pass
        return urlunsplit((u.scheme, netloc, u.path, u.query, u.fragment))

    out = url
    for key in ("password", "user"):
        out = re.sub(rf"({key}\s*=\s*)\S+", r"\1***", out)
    return out


def mask_text(text: str) -> str:
    """把任意文本里嵌入的凭据打码（错误信息落日志 / 进 /health 前统一过一遍）。"""
    return _CRED_RE.sub("://***:***@", text or "")


def target(url: str) -> str:
    """`host:port/dbname`（不含任何凭据）——/health、doctor、备份脚本展示用。"""
    p = _parts(url)
    return f"{p.get('host') or 'localhost'}:{p.get('port') or '5432'}/{p.get('dbname') or '?'}"


def dbname(url: str) -> str:
    """库名（备份脚本据此决定备份哪个库——必须来自本单源，不能写死）。"""
    return _parts(url).get("dbname") or ""


def host_port(url: str) -> tuple:
    p = _parts(url)
    return (p.get("host") or "localhost", str(p.get("port") or "5432"))


def with_dbname(url: str, dbname_new: str) -> str:
    """同主机同凭据、换库名的连接串（体检/建库用：连 admin 库 postgres 查库清单）。

    凭据原样保留——doctor 用它在不额外索要密码的前提下探服务可用性。
    注意：调用方展示时必须经 safe_url() 脱敏。
    """
    if "://" in url:
        from urllib.parse import urlsplit, urlunsplit

        u = urlsplit(url)
        return urlunsplit((u.scheme, u.netloc, f"/{dbname_new}", u.query, u.fragment))

    if re.search(r"\bdbname\s*=", url):
        return re.sub(r"\bdbname\s*=\s*[^\s]+", f"dbname={dbname_new}", url)
    return (url + " " + f"dbname={dbname_new}").strip()


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    url = resolve_db_url()
    if "--safe" in args:
        print(safe_url(url))
    elif "--target" in args:
        print(target(url))
    elif "--dbname" in args:
        print(dbname(url))
    elif "--host" in args:
        print(host_port(url)[0])
    elif "--port" in args:
        print(host_port(url)[1])
    elif "--backend" in args:
        print(resolve_store_backend())
    else:
        print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
