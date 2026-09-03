"""本地存储层 — 任务的持久化 store。

为 web_server 的多任务会话提供统一的 store 接口：
- `BaseStore`: 抽象接口（契约）
- `MemoryStore`: 进程内实现（测试 / PG 不可用时降级）
- `PostgresStore`: psycopg3 实现，落盘本机 PostgreSQL（Task 3 补齐）

**边界**：本模块只负责「任务的元数据 + 参数快照 + 消息历史」的存取，
不碰引擎逻辑。`session_state.py` 仍是运行时唯一真相源，本模块是持久化副本。

**软删**：`delete_task` 只置 `deleted_at`（归档），不物理删除消息。
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import List, Optional

import psycopg



class BaseStore:
    """store 统一接口。所有实现须提供这些方法。"""

    def create_task(self, name: str) -> dict:
        raise NotImplementedError

    def list_tasks(self) -> List[dict]:
        raise NotImplementedError

    def get_task(self, task_id: str) -> Optional[dict]:
        raise NotImplementedError

    def rename_task(self, task_id: str, name: str) -> None:
        raise NotImplementedError

    def update_params(self, task_id: str, params: dict) -> None:
        raise NotImplementedError

    def add_message(self, task_id: str, role: str, content: str, turn: int = 0) -> None:
        raise NotImplementedError

    def get_messages(self, task_id: str) -> List[dict]:
        raise NotImplementedError

    def delete_task(self, task_id: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        """释放底层资源（如数据库连接）。内存版为空操作。"""


# 单任务消息数上限，防止长期运行内存无限增长
_MAX_MESSAGES_PER_TASK = 500


class MemoryStore(BaseStore):
    """进程内实现，测试与降级用。"""

    def __init__(self) -> None:
        self._tasks: dict = {}
        self._msgs: dict = {}

    def create_task(self, name: str) -> dict:
        tid = str(uuid.uuid4())
        now = time.time()
        t = {
            "id": tid,
            "name": name,
            "params": {},
            "industry": None,
            "turn": 0,
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        }
        self._tasks[tid] = t
        self._msgs[tid] = []
        return dict(t)

    def list_tasks(self) -> List[dict]:
        return [dict(t) for t in self._tasks.values() if t["deleted_at"] is None]

    def get_task(self, task_id: str) -> Optional[dict]:
        t = self._tasks.get(task_id)
        return dict(t) if t else None

    def rename_task(self, task_id: str, name: str) -> None:
        if task_id in self._tasks:
            self._tasks[task_id]["name"] = name
            self._tasks[task_id]["updated_at"] = time.time()

    def update_params(self, task_id: str, params: dict) -> None:
        if task_id in self._tasks:
            self._tasks[task_id]["params"] = dict(params or {})
            self._tasks[task_id]["updated_at"] = time.time()

    def add_message(self, task_id: str, role: str, content: str, turn: int = 0) -> None:
        if task_id in self._msgs:
            self._msgs[task_id].append(
                {"role": role, "content": content, "turn": turn}
            )
            # R1 修复：限制单任务消息数上限，超出淘汰最旧
            if len(self._msgs[task_id]) > _MAX_MESSAGES_PER_TASK:
                self._msgs[task_id] = self._msgs[task_id][-_MAX_MESSAGES_PER_TASK:]

    def get_messages(self, task_id: str) -> List[dict]:
        return [dict(m) for m in self._msgs.get(task_id, [])]

    def delete_task(self, task_id: str) -> None:
        if task_id in self._tasks:
            self._tasks[task_id]["deleted_at"] = time.time()
            self._tasks[task_id]["updated_at"] = time.time()
            # R1 修复：软删任务时同步清理消息，防内存泄漏
            self._msgs.pop(task_id, None)

    def close(self) -> None:
        pass


# ── 数据库连接配置 ────────────────────────────────────────────────────────
_DEFAULT_DB_URL = "postgresql://newmacbook@localhost:5432/shangzhu"


def _db_url() -> str:
    """获取业务库连接串（PGDATABASE_URL 优先，否则本机默认）。"""
    return os.getenv("PGDATABASE_URL") or _DEFAULT_DB_URL


def _row_to_task(row) -> dict:
    """把 tasks 表的行转成与 MemoryStore 对齐的 dict。"""
    return {
        "id": str(row[0]),
        "name": row[1],
        "params": row[2] if row[2] else {},
        "industry": row[3],
        "turn": row[4] if row[4] is not None else 0,
        "created_at": row[5],
        "updated_at": row[6],
        "deleted_at": row[7],
    }


class PostgresStore(BaseStore):
    """psycopg3 实现，落盘本机 PostgreSQL。

    使用单连接 + autocommit（本地单用户够用，不做连接池）。
    """

    def __init__(self, url: Optional[str] = None) -> None:
        self.url = url or _db_url()
        self._conn = psycopg.connect(self.url, autocommit=True)

    def create_task(self, name: str) -> dict:
        tid = str(uuid.uuid4())
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tasks (id, name) VALUES (%s, %s) RETURNING id, name",
                (tid, name),
            )
        return {
            "id": tid,
            "name": name,
            "params": {},
            "industry": None,
            "turn": 0,
            "created_at": None,
            "updated_at": None,
            "deleted_at": None,
        }

    def list_tasks(self) -> List[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, params, industry, turn, created_at, updated_at, deleted_at "
                "FROM tasks WHERE deleted_at IS NULL ORDER BY updated_at DESC"
            )
            rows = cur.fetchall()
        return [_row_to_task(r) for r in rows]

    def get_task(self, task_id: str) -> Optional[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, params, industry, turn, created_at, updated_at, deleted_at "
                "FROM tasks WHERE id = %s",
                (task_id,),
            )
            row = cur.fetchone()
        return _row_to_task(row) if row else None

    def rename_task(self, task_id: str, name: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET name = %s, updated_at = now() WHERE id = %s",
                (name, task_id),
            )

    def update_params(self, task_id: str, params: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET params = %s, updated_at = now() WHERE id = %s",
                (json.dumps(params or {}), task_id),
            )

    def add_message(self, task_id: str, role: str, content: str, turn: int = 0) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (task_id, role, content, turn) VALUES (%s, %s, %s, %s)",
                (task_id, role, content, turn),
            )

    def get_messages(self, task_id: str) -> List[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT role, content, turn FROM messages "
                "WHERE task_id = %s ORDER BY id",
                (task_id,),
            )
            rows = cur.fetchall()
        return [{"role": r[0], "content": r[1], "turn": r[2]} for r in rows]

    def delete_task(self, task_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET deleted_at = now(), updated_at = now() WHERE id = %s",
                (task_id,),
            )

    def close(self) -> None:
        self._conn.close()


# ── store 工厂 ────────────────────────────────────────────────────────────
_store: Optional[BaseStore] = None


def get_store() -> BaseStore:
    """全局单例 store：优先 PG，连不上/未配置时降级内存。

    降级日志打一次，避免刷屏；重试逻辑由上层决定（如 web_server 启动时探测）。
    """
    global _store
    if _store is not None:
        return _store
    try:
        _store = PostgresStore()
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning(f"PG 不可用，降级内存 store: {e}")
        _store = MemoryStore()
    return _store


def reset_store_for_tests() -> None:
    """清空单例（测试隔离用）。"""
    global _store
    _store = None
