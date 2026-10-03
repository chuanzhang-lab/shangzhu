"""pytest 全局隔离闸（M-01）——测试绝不触碰真实数据。

背景：历史上 tests/ 直写真实 PG（test_task_api 等只 patch 了 web_server.get_store，
storage.local_store.get_store 照样打真库），任务表积压 70+ 条测试残留。

隔离策略（两级，自动选择）：
1. **测试库优先**：PG 可达时自动建/连 `shangzhu_test` 测试库（PGDATABASE_URL 指向它），
   PostgresStore 端到端用例照常覆盖，只是打在测试库上；
2. **PG 不可用**：PGDATABASE_URL 指向必败地址（端口 1 秒级 ECONNREFUSED），
   get_store() 降级到 LocalFileStore，且 LOCAL_STORE_PATH 强制指向临时目录——
   离线/无 PG 环境照样全量可跑、零外部依赖。

三闸兜底（每个用例前后自动执行）：
- 环境变量被个别用例 pop/篡改后（如 test_config_priority）自动恢复；
- 每个用例前 reset_store_for_tests()，杜绝单例缓存住错误后端；
- test_isolation_guard.py 断言测试期 store 永不指向真实库。
"""
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

# ── 测试库连接串：PG 可达则连测试库，不可达则给必败地址（快速失败→自动降级）──
_TEST_DB_NAME = "shangzhu_test"
_FALLBACK_DB_URL = "postgresql://nobody@127.0.0.1:1/shangzhu_test"  # 必败且快败

# 测试专用临时目录（LocalFileStore / 文件类测试的统一落点）
TEST_TMP_DIR = tempfile.mkdtemp(prefix="shangzhu-tests-")
os.environ["LOCAL_STORE_PATH"] = TEST_TMP_DIR


def _try_prepare_test_db() -> str:
    """尝试确保测试库存在，返回测试库连接串；PG 不可用返回必败地址。"""
    try:
        import psycopg

        base_url = f"postgresql://{os.environ.get('USER', 'postgres')}@localhost:5432/postgres"
        with psycopg.connect(base_url, connect_timeout=2) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (_TEST_DB_NAME,))
                if cur.fetchone() is None:
                    cur.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
        return f"postgresql://{os.environ.get('USER', 'postgres')}@localhost:5432/{_TEST_DB_NAME}"
    except Exception:  # noqa: BLE001 —— PG 不存在/无权限：走降级，测试照跑
        return _FALLBACK_DB_URL


PGDATABASE_URL_UNDER_TEST = _try_prepare_test_db()
os.environ["PGDATABASE_URL"] = PGDATABASE_URL_UNDER_TEST


@pytest.fixture(autouse=True)
def _isolate_store_env():
    """每个用例前后：恢复隔离环境变量 + 清 store 单例（防用例间互相污染）。"""
    os.environ["PGDATABASE_URL"] = PGDATABASE_URL_UNDER_TEST
    os.environ["LOCAL_STORE_PATH"] = TEST_TMP_DIR
    try:
        from storage.local_store import reset_store_for_tests

        reset_store_for_tests()
    except Exception:  # noqa: BLE001
        pass
    yield
    try:
        from storage.local_store import reset_store_for_tests

        reset_store_for_tests()
    except Exception:  # noqa: BLE001
        pass
