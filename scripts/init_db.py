"""初始化本机 PostgreSQL — 幂等建库建表。

为本地创业者工作台创建 `shangzhu` 库及 tasks / messages 表。

用法：
    .venv/bin/python scripts/init_db.py

依赖：psycopg 3（已在 .venv）。可重复执行（CREATE IF NOT EXISTS）。
"""
import getpass
import os
import sys

# DDL 单源：与 PostgresStore 启动时的幂等建表共用同一份 SCHEMA_SQL，
# 不再本文件各存一份（两处 DDL 一旦漂移，会出现「init_db 建的表 != 服务用的表」）。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import psycopg  # noqa: E402

from storage.local_store import SCHEMA_SQL  # noqa: E402

# 免密本地连接默认用当前系统用户名（peer auth），不绑定某台机器；可用环境变量覆盖。
_LOCAL_USER = getpass.getuser()

# 管理员连接（默认连 postgres 库，用于建库）。可用 PGADMIN_URL 覆盖。
DEFAULT_ADMIN_URL = f"postgresql://{_LOCAL_USER}@localhost:5432/postgres"
DB_NAME = "shangzhu"

# 业务连接（建表用）。可用 PGDATABASE_URL 覆盖。
DEFAULT_URL = f"postgresql://{_LOCAL_USER}@localhost:5432/{DB_NAME}"

def ensure_db() -> None:
    """若目标库不存在则创建（幂等）。"""
    admin_url = os.getenv("PGADMIN_URL") or DEFAULT_ADMIN_URL
    conn = psycopg.connect(admin_url, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{DB_NAME}"')
    finally:
        conn.close()


def ensure_tables() -> None:
    """在业务库内创建表（幂等）。DDL 取自 storage.local_store.SCHEMA_SQL 单源。"""
    url = os.getenv("PGDATABASE_URL") or DEFAULT_URL
    conn = psycopg.connect(url, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
    finally:
        conn.close()
    print(f"[init_db] OK — DB={DB_NAME} 表就绪")


def main() -> None:
    ensure_db()
    ensure_tables()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"[init_db] 失败: {e}", file=sys.stderr)
        sys.exit(1)
