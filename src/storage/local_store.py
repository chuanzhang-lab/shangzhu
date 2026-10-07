"""本地存储层 — 任务的持久化 store。

为 web_server 的多任务会话提供统一的 store 接口：
- `BaseStore`: 抽象接口（契约）
- `PostgresStore`: psycopg3 实现，落盘本机 PostgreSQL（**首选**）
- `LocalFileStore`: JSON 文件实现（PG 不可用时的降级，**重启不丢**）
- `MemoryStore`: 进程内实现（**仅测试用**，重启即丢）

**降级链**（`get_store()`）：PostgresStore → LocalFileStore → MemoryStore。
前两级都能跨重启存活；只有 MemoryStore 会丢数据，且它只在「PG 不可用 +
本地文件也写不了」时兜底，届时打 ERROR 级日志。

**边界**：本模块只负责「任务的元数据 + 参数快照 + 消息历史」的存取，
不碰引擎逻辑。`session_state.py` 仍是运行时唯一真相源，本模块是持久化副本。

**软删**：`delete_task` 只置 `deleted_at`（归档），不物理删除消息。

**历史教训（2026-08-30，2026-09-27 二次确认）**：psycopg 一度只声明在可选依赖组（旧 extra）里，
`uv sync` 把它从 .venv 剪掉 → `import psycopg` 失败 → 静默降级内存 store →
任务栏数据重启即丢，且降级日志没落盘（用的是模块 logger，没挂 handler），
排查时日志里一行痕迹都没有。现改为：
1. psycopg 进主依赖（护栏见 tests/test_persistence_guard.py）；
2. 降级日志挂到 `web.local_store`（继承 web_server 的控制台+文件 handler）；
3. 降级目标从「内存」换成「本地 JSON 文件」，即使没有 PG 也不丢数据。
"""
from __future__ import annotations

import getpass
import json
import logging
import os
import time
import threading
import uuid
from typing import List, Optional

# 挂到 web_server 配置的 "web" logger 之下，继承其控制台 + logs/web_server.log
# 双通道 handler——降级原因必须能在日志文件里查到，不能只走 stderr 的 lastResort。
logger = logging.getLogger("web.local_store")


class StoreUnavailableError(RuntimeError):
    """存储后端不可用（连接建立失败，或语句执行中连接失效且**不可安全重试**）。

    2026-10-07 加固（Z2）：把「连接层不可用」从裸的 OperationalError 里分离出来，
    调用方据此区分「稍后重试可能成功」与「请求本身有问题」。错误原文只进日志
    （web_server 侧统一固定文案回客户端），不透传给用户。
    """

# 注意：psycopg 不在模块顶层导入。
# 顶层 import psycopg 会让「最小依赖」声明失真——未装 Postgres 驱动时 import 即崩。
# 改为在 PostgresStore 内部延迟导入，保证无驱动时服务仍能降级启动。


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

    def add_turn(self, task_id: str, user_msg: str, assistant_msg: str,
                 params: Optional[dict] = None, turn: int = 0) -> None:
        """原子写入一轮对话：user 消息 + assistant 消息 + params 快照。

        2026-10-07 加固（L1/T1）：此前调用方分三次调 store（2×add_message +
        update_params），而储存实现是 autocommit——三次各自成事务，崩在中间
        就留下「有问无答 + params 陈旧」的半回合。把事务边界收进契约层，
        调用方不必（也无法）自己表达。

        实现约定：三者全写或全不写；params=None 表示本轮不改参数快照。
        """
        raise NotImplementedError

    def get_messages(self, task_id: str) -> List[dict]:
        raise NotImplementedError

    def delete_task(self, task_id: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        """释放底层资源（如数据库连接）。内存版为空操作。"""


# 单任务消息数上限，防止长期运行内存无限增长
_MAX_MESSAGES_PER_TASK = 500


def _log_trim(task_id: str, dropped: int) -> None:
    """消息裁剪必须留痕（Z3，2026-10-07 加固）。

    裁剪曾是三条静默丢数据路径里唯一完全无日志的一条：超过上限的最旧消息
    被删掉，用户与日志都无从知晓。工程公约「降级必有痕」覆盖此处。
    """
    if dropped:
        logger.warning(
            f"任务 {task_id} 消息数超上限 {_MAX_MESSAGES_PER_TASK}，"
            f"已裁剪最旧 {dropped} 条（不再落盘）"
        )


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
            dropped = max(0, len(self._msgs[task_id]) - _MAX_MESSAGES_PER_TASK)
            if dropped:
                self._msgs[task_id] = self._msgs[task_id][-_MAX_MESSAGES_PER_TASK:]
                _log_trim(task_id, dropped)

    def add_turn(self, task_id: str, user_msg: str, assistant_msg: str,
                 params: Optional[dict] = None, turn: int = 0) -> None:
        """原子写一轮（内存版：三次 dict 操作之间无 I/O，不存在半回合）。"""
        if task_id not in self._msgs:
            logger.warning(f"add_turn 目标任务不存在，本轮未入内存 store: {task_id}")
            return
        self.add_message(task_id, "user", user_msg, turn)
        self.add_message(task_id, "assistant", assistant_msg, turn)
        if params is not None:
            self.update_params(task_id, params)

    def get_messages(self, task_id: str) -> List[dict]:
        return [dict(m) for m in self._msgs.get(task_id, [])]

    def delete_task(self, task_id: str) -> None:
        if task_id in self._tasks:
            self._tasks[task_id]["deleted_at"] = time.time()
            self._tasks[task_id]["updated_at"] = time.time()
            self._msgs.pop(task_id, None)

    def close(self) -> None:
        pass


# ── 本地 JSON 文件 store（PG 不可用时的持久化降级）──────────────────────────
# 放在仓库根的 data/ 下，跨进程重启存活。写盘用「临时文件 + os.replace」原子
# 替换，避免写到一半崩溃留下半截 JSON 把整个 store 打坏。


def _file_store_path() -> str:
    """本地文件 store 路径。可用 LOCAL_STORE_PATH 覆盖（测试用临时目录）。

    以 __file__ 定位仓库根，不依赖 cwd——web_server 启动时会 chdir 到 src/。
    """
    override = os.getenv("LOCAL_STORE_PATH")
    if override:
        return override
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "data", "local_store.json")


class LocalFileStore(BaseStore):
    """JSON 文件实现：PG 不可用时的降级目标，**重启不丢数据**。

    内存 dict 作读写缓存，每次写操作后整量落盘（本地单用户量级，代价可忽略）。
    与 MemoryStore 的区别只有「落盘」——对外契约完全一致。
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or _file_store_path()
        self._tasks: dict = {}
        self._msgs: dict = {}
        # 审查修复 F2：降级路径下多线程并发写同一 JSON 文件，固定 tmp 名会互相
        # 覆盖/替换失败。实例锁串行化所有写操作（含 _flush），本地单用户量级
        # 锁竞争可忽略。
        self._lock = threading.Lock()
        self._tighten_perms()
        self._load()

    def _tighten_perms(self) -> None:
        """把 store 文件权限收紧到 0600（属主可读写）。

        隐私考量（2026-10-07 存储加固）：本文件含任务名、参数快照（租金额、
        客单价等经营数据）与完整对话历史，早期版本以默认 umask 落盘（644）——
        同机其他账户可读。已存在的历史文件在下一次启动时一并收紧。
        """
        if os.path.isfile(self.path):
            try:
                os.chmod(self.path, 0o600)
            except OSError as e:
                logger.warning(f"本地 store 文件权限收紧失败（不影响读写）: {e}")

    def _load(self) -> None:
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._tasks = data.get("tasks") or {}
            self._msgs = data.get("msgs") or {}
        except Exception as e:  # noqa: BLE001
            backup = f"{self.path}.corrupt-{int(time.time())}"
            try:
                os.replace(self.path, backup)
                logger.error(f"本地 store 文件损坏，已备份到 {backup}，从空 store 重启: {e}")
            except OSError:
                logger.error(f"本地 store 文件损坏且备份失败: {e}")
            self._tasks, self._msgs = {}, {}

    def _flush(self) -> None:
        """原子落盘：写 .tmp 后 os.replace，杜绝半截 JSON。调用方须持 self._lock。"""
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        # 唯一 tmp 名：即使锁外被调用（防御），也不会与其他线程的 tmp 冲突
        tmp = f"{self.path}.{threading.get_ident()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {"tasks": self._tasks, "msgs": self._msgs},
                    f, ensure_ascii=False,
                )
            # 权限随 os.replace 一起生效：先收紧 tmp，再替换，避免出现
            # 「新文件以 644 短暂可见」的窗口（隐私，见 _tighten_perms）。
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)
        finally:
            # 兏底清理：replace 成功后 tmp 已不存在，失败时也把残留 tmp 删掉
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def create_task(self, name: str) -> dict:
        with self._lock:
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
            self._flush()
            return dict(t)

    def list_tasks(self) -> List[dict]:
        # GIL 下 dict.values() 迭代期间另一线程写 dict 会 RuntimeError：
        # 拷贝到列表的操作也入锁
        with self._lock:
            return [dict(t) for t in self._tasks.values() if t.get("deleted_at") is None]

    def get_task(self, task_id: str) -> Optional[dict]:
        with self._lock:
            t = self._tasks.get(task_id)
            return dict(t) if t else None

    def rename_task(self, task_id: str, name: str) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["name"] = name
                self._tasks[task_id]["updated_at"] = time.time()
                self._flush()

    def update_params(self, task_id: str, params: dict) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["params"] = dict(params or {})
                self._tasks[task_id]["updated_at"] = time.time()
                self._flush()

    def add_message(self, task_id: str, role: str, content: str, turn: int = 0) -> None:
        with self._lock:
            if task_id in self._msgs:
                self._msgs[task_id].append(
                    {"role": role, "content": content, "turn": turn}
                )
                dropped = max(0, len(self._msgs[task_id]) - _MAX_MESSAGES_PER_TASK)
                if dropped:
                    self._msgs[task_id] = self._msgs[task_id][-_MAX_MESSAGES_PER_TASK:]
                self._flush()
                _log_trim(task_id, dropped)

    def add_turn(self, task_id: str, user_msg: str, assistant_msg: str,
                 params: Optional[dict] = None, turn: int = 0) -> None:
        """原子写一轮（文件版：整轮改完只 _flush 一次，失败回滚内存态）。

        对照旧路径（add_message ×2 + update_params 各 _flush 一次）：崩在第 2 次
        会留下「有问无答」的文件，且第 3 次未执行时 params 快照与消息不匹配。

        全不写：落盘抛错（如 params 不可 JSON 序列化）时把内存缓存回滚到改动前，
        再抛出——否则内存与磁盘会静默分叉，且此后每次 _flush 都失败。
        """
        with self._lock:
            if task_id not in self._msgs:
                logger.warning(f"add_turn 目标任务不存在，本轮未入文件 store: {task_id}")
                return
            prev_msgs = list(self._msgs[task_id])
            prev_params = dict((self._tasks.get(task_id) or {}).get("params") or {})
            try:
                self._msgs[task_id].append({"role": "user", "content": user_msg, "turn": turn})
                self._msgs[task_id].append({"role": "assistant", "content": assistant_msg, "turn": turn})
                dropped = max(0, len(self._msgs[task_id]) - _MAX_MESSAGES_PER_TASK)
                if dropped:
                    self._msgs[task_id] = self._msgs[task_id][-_MAX_MESSAGES_PER_TASK:]
                if params is not None and task_id in self._tasks:
                    self._tasks[task_id]["params"] = dict(params or {})
                    self._tasks[task_id]["updated_at"] = time.time()
                self._flush()
            except Exception:
                self._msgs[task_id] = prev_msgs
                if task_id in self._tasks:
                    self._tasks[task_id]["params"] = prev_params
                raise
            _log_trim(task_id, dropped)

    def get_messages(self, task_id: str) -> List[dict]:
        with self._lock:
            return [dict(m) for m in self._msgs.get(task_id, [])]

    def delete_task(self, task_id: str) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["deleted_at"] = time.time()
                self._tasks[task_id]["updated_at"] = time.time()
                self._msgs.pop(task_id, None)
                self._flush()

    def ping(self) -> None:
        """可写性自检。构造后调用一次，确认路径真能落盘。"""
        with self._lock:
            self._flush()

    def close(self) -> None:
        pass


# ── 数据库连接配置 ────────────────────────────────────────────────────────
# 默认走本机当前用户名的免密 peer 连接（与 README「<系统用户名>」口径一致），
# 可被 PGDATABASE_URL / config/storage.json 的 db_url 覆盖。
_DEFAULT_DB_URL = f"postgresql://{getpass.getuser()}@localhost:5432/shangzhu"

# ── 连接层失败预算（2026-10-07 加固 S1/Z1）────────────────────────────────
# 缺这三条超时时，PG 半开/wedged 会让一次卡住的查询永久占住 _conn_lock，
# 全部任务 API 连 /health 一起冻死——本地单用户场景下唯一能把「部分失败」
# 放大成「整体不可用」的点。
_CONNECT_TIMEOUT_S = 5           # 建立连接上限：PG 不可达时不再无限等（libpq 默认可到 75s+）
_STATEMENT_TIMEOUT_MS = 10_000   # 单条 SQL 上限：卡住的查询必须自己死掉并释放锁
_LOCK_TIMEOUT_MS = 5_000         # 等表锁上限
_IDLE_TX_TIMEOUT_MS = 30_000     # 事务闲置上限：漏掉的 BEGIN 不占着快照不放


def _pg_connect_params(url: str) -> dict:
    """构造 psycopg.connect 的失败预算参数（超时 + TCP keepalive）。

    DSN 里已显式给出的同名参数一律尊重、不覆盖——既避免与用户配置打架，
    也绕开 libpq 重复键的取值歧义（libpq 遇到重复键只认第一个）。
    """
    params: dict = {}
    low = url.lower()
    if "connect_timeout" not in low:
        params["connect_timeout"] = _CONNECT_TIMEOUT_S
    if "options=" not in low:
        params["options"] = (
            f"-c statement_timeout={_STATEMENT_TIMEOUT_MS} "
            f"-c lock_timeout={_LOCK_TIMEOUT_MS} "
            f"-c idle_in_transaction_session_timeout={_IDLE_TX_TIMEOUT_MS}"
        )
    if "keepalives" not in low:
        params.update(
            keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
        )
    return params


# ── 表结构（DDL 单源）────────────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '新任务',
    params JSONB NOT NULL DEFAULT '{}',
    industry TEXT,
    turn INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    turn INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_task ON messages(task_id);
"""


def _db_url() -> str:
    """获取业务库连接串，三级优先级：env var → config file → 内置默认。"""
    env_url = os.getenv("PGDATABASE_URL")
    if env_url and env_url.strip():
        return env_url.strip()

    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config", "storage.json",
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        file_url = (cfg.get("db_url") or "").strip()
        if file_url:
            return file_url
    except (OSError, json.JSONDecodeError):
        pass

    return _DEFAULT_DB_URL


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


def _trim_messages(cur, task_id: str) -> int:
    """裁剪单任务超额的最旧消息，返回删除条数（0 = 未触发裁剪）。

    R2 修复（单任务上限 500，防 messages 表无限增长）。2026-10-07 加固 Z3：
    返回条数供调用方留痕——裁剪曾是三条静默丢数据路径里唯一零日志的一条。
    """
    cur.execute(
        "DELETE FROM messages WHERE task_id = %s AND id NOT IN ("
        "SELECT id FROM messages WHERE task_id = %s "
        "ORDER BY id DESC LIMIT %s)",
        (task_id, task_id, _MAX_MESSAGES_PER_TASK),
    )
    return cur.rowcount or 0


class PostgresStore(BaseStore):
    """psycopg3 实现，落盘本机 PostgreSQL（持久化首选）。

    使用单连接 + autocommit（本地单用户够用，不做连接池）。相比早期版本有五处加固：

    1. **懒连接**：`__init__` 只存 URL，不建连接——避免「服务启动顺序」与
       「PG 临时不可达」互相纠缠，也让 `get_store()` 能靠 `ping()` 真正验证可用性。
    2. **失败预算**：连接/语句/锁三重超时 + TCP keepalive（`_pg_connect_params`）。
       没有它，一次卡住的查询会永久占住 `_conn_lock`，全站（含 /health）一起冻。
    3. **重试分读写**：连接没建立就失败→无条件重试一次；语句已发出后只有读重试，
       写不重试（避免「提交成功但响应丢失」被重放成重复消息）。
    4. **原子回合**：`add_turn` 单事务写 user + assistant + params 快照 + 裁剪。
    5. **幂等建表**：首次连上时执行 `SCHEMA_SQL`（CREATE IF NOT EXISTS），
       消除「忘了跑 scripts/init_db.py 就静默没表」的失败模式。
    """

    def __init__(self, url: Optional[str] = None) -> None:
        import psycopg  # 延迟导入：仅真正使用 Postgres 时才需要该驱动

        self._psycopg = psycopg
        self.url = url or _db_url()
        self._conn = None
        self._schema_ready = False
        # 审查修复 F9：psycopg 连接非线程安全，单连接原依赖「store 操作全在
        # 事件循环线程串行」的隐式契约。加锁后即使未来把 store 写丢进
        # asyncio.to_thread 或改多 worker，也不会交错用同一连接。
        self._conn_lock = threading.Lock()

    def _connect(self) -> None:
        # 失败预算（超时 / TCP keepalive）见 _pg_connect_params；DSN 显式值优先。
        self._conn = self._psycopg.connect(
            self.url, autocommit=True, **_pg_connect_params(self.url)
        )
        if not self._schema_ready:
            with self._conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
            self._schema_ready = True

    def _drop_conn(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _execute(self, fn, *, retry_statement: bool = False, transaction: bool = False):
        """执行一段以 cursor 为参数的 SQL。

        审查修复 F9：全程持连接锁，串行化所有 SQL（含断线重连），
        防止多线程共享单连接交错执行。本地单用户量级锁竞争可忽略。

        重试语义（2026-10-07 加固 Z2）——「安全重试」与「可能已提交」必须分开：
        - 连接还没建立就失败：语句肯定没发出去 → 无条件重试一次（PG 未起/刚重启
          这类最常见故障走这条）；
        - 语句已发出后失败：读幂等（retry_statement=True）→ 重试安全；
          写（默认 False）→ **不重试**。提交成功但响应丢失时重试会重复插入
          （消息翻倍 / 重复任务），宁可抛 StoreUnavailableError 让用户重试。
        - transaction=True：整段 fn 包进一个事务（多语句写的原子性，加固 L1）。

        失败一律收敛为 StoreUnavailableError（错误原文只进日志）。
        """
        last_err: Optional[Exception] = None
        conn_was_down = True
        with self._conn_lock:
            for attempt in (0, 1):
                conn_was_down = self._conn is None or self._conn.closed
                try:
                    if conn_was_down:
                        self._connect()
                    if transaction:
                        with self._conn.transaction():
                            with self._conn.cursor() as cur:
                                return fn(cur)
                    with self._conn.cursor() as cur:
                        return fn(cur)
                except (self._psycopg.OperationalError,
                        self._psycopg.InterfaceError) as e:
                    last_err = e
                    self._drop_conn()
                    if attempt == 0 and (conn_was_down or retry_statement):
                        logger.warning(f"PG 连接失效，重连重试: {e}")
                        continue
                    break
        raise StoreUnavailableError(
            "PostgreSQL 不可用（"
            + ("连接建立失败" if conn_was_down else "语句执行中连接失效")
            + f"）：{last_err}"
        ) from last_err

    def ping(self) -> None:
        """连通性自检（含幂等建表）。构造后调用一次，确认后端真能用。"""
        self._execute(lambda cur: cur.execute("SELECT 1"), retry_statement=True)

    def create_task(self, name: str) -> dict:
        tid = str(uuid.uuid4())

        def _run(cur):
            cur.execute(
                "INSERT INTO tasks (id, name) VALUES (%s, %s) "
                "RETURNING created_at, updated_at",
                (tid, name),
            )
            return cur.fetchone()

        row = self._execute(_run)
        return {
            "id": tid,
            "name": name,
            "params": {},
            "industry": None,
            "turn": 0,
            "created_at": row[0] if row else None,
            "updated_at": row[1] if row else None,
            "deleted_at": None,
        }

    def list_tasks(self) -> List[dict]:
        def _run(cur):
            cur.execute(
                "SELECT id, name, params, industry, turn, created_at, updated_at, deleted_at "
                "FROM tasks WHERE deleted_at IS NULL ORDER BY updated_at DESC"
            )
            return cur.fetchall()

        return [_row_to_task(r) for r in self._execute(_run, retry_statement=True)]

    def get_task(self, task_id: str) -> Optional[dict]:
        def _run(cur):
            cur.execute(
                "SELECT id, name, params, industry, turn, created_at, updated_at, deleted_at "
                "FROM tasks WHERE id = %s",
                (task_id,),
            )
            return cur.fetchone()

        row = self._execute(_run, retry_statement=True)
        return _row_to_task(row) if row else None

    def rename_task(self, task_id: str, name: str) -> None:
        self._execute(lambda cur: cur.execute(
            "UPDATE tasks SET name = %s, updated_at = now() WHERE id = %s",
            (name, task_id),
        ))

    def update_params(self, task_id: str, params: dict) -> None:
        self._execute(lambda cur: cur.execute(
            "UPDATE tasks SET params = %s, updated_at = now() WHERE id = %s",
            (json.dumps(params or {}), task_id),
        ))

    def add_message(self, task_id: str, role: str, content: str, turn: int = 0) -> None:
        def _run(cur):
            cur.execute(
                "INSERT INTO messages (task_id, role, content, turn) VALUES (%s, %s, %s, %s)",
                (task_id, role, content, turn),
            )
            # R2：单任务消息上限 500，超限删最旧。加固 L1：INSERT 与裁剪 DELETE
            # 收进同一事务——旧版两语句各自 autocommit，崩在中间会留下
            # 「已插入但未裁剪」的超限状态。
            return _trim_messages(cur, task_id)

        _log_trim(task_id, self._execute(_run, transaction=True) or 0)

    def add_turn(self, task_id: str, user_msg: str, assistant_msg: str,
                 params: Optional[dict] = None, turn: int = 0) -> None:
        """原子写一轮（PG 版：单事务内 INSERT user + INSERT assistant + UPDATE params + 裁剪）。

        2026-10-07 加固 L1/T1：此前调用方三次独立调用 = 三个事务，崩在中间留下
        「有问无答 + params 陈旧」的半回合——用户看到的与落盘的从此可以不一致。
        本方法把整轮收进一个事务：要么全落盘，要么全不落盘。
        """
        def _run(cur):
            cur.execute(
                "INSERT INTO messages (task_id, role, content, turn) VALUES (%s, 'user', %s, %s)",
                (task_id, user_msg, turn),
            )
            cur.execute(
                "INSERT INTO messages (task_id, role, content, turn) VALUES (%s, 'assistant', %s, %s)",
                (task_id, assistant_msg, turn),
            )
            if params is not None:
                cur.execute(
                    "UPDATE tasks SET params = %s, updated_at = now() WHERE id = %s",
                    (json.dumps(params or {}), task_id),
                )
            return _trim_messages(cur, task_id)

        _log_trim(task_id, self._execute(_run, transaction=True) or 0)

    def get_messages(self, task_id: str) -> List[dict]:
        def _run(cur):
            cur.execute(
                "SELECT role, content, turn FROM messages "
                "WHERE task_id = %s ORDER BY id",
                (task_id,),
            )
            return cur.fetchall()

        return [{"role": r[0], "content": r[1], "turn": r[2]}
                for r in self._execute(_run, retry_statement=True)]

    def delete_task(self, task_id: str) -> None:
        self._execute(lambda cur: cur.execute(
            "UPDATE tasks SET deleted_at = now(), updated_at = now() WHERE id = %s",
            (task_id,),
        ))

    def close(self) -> None:
        self._drop_conn()


# ── store 工厂 ────────────────────────────────────────────────────────────
_store: Optional[BaseStore] = None


_store_lock = threading.Lock()  # 审查修复 F8：防并发首次初始化创建多个实例

def get_store() -> BaseStore:
    """全局单例 store：PG → 本地 JSON 文件 → 内存（最后一档才丢数据）。

    **降级必有痕**：每一档降级都经 `web.local_store` logger 打 WARNING/ERROR，
    继承 web_server 的控制台 + `logs/web_server.log` 双通道，排查时能直接查到原因。
    """
    global _store
    if _store is not None:
        return _store
    # 双重检查锁：并发首次调用只有一个线程执行降级链（尤其降级路径，
    # 多个 LocalFileStore 实例指向同一 JSON 文件会互相覆盖）
    with _store_lock:
        if _store is not None:
            return _store

        # 1) PostgreSQL：持久化首选
        candidate: Optional[BaseStore] = None
        try:
            pg = PostgresStore()
            pg.ping()
            candidate = pg
        except Exception as e:  # noqa: BLE001
            logger.warning(f"PostgreSQL 不可用（{e}），降级本地文件 store")
            if candidate is not None:
                candidate.close()

        # 2) 本地 JSON 文件：PG 不在也不丢数据
        if candidate is None:
            try:
                fs = LocalFileStore()
                fs.ping()
                candidate = fs
                logger.warning(f"已降级本地文件 store：{fs.path}（重启不丢，但非多端共享）")
                logger.warning(
                    "孤儿数据提醒：本批任务只写进上面的 JSON 文件；PG 恢复后 get_store() 会"
                    "切回 PostgreSQL，该文件数据不会自动迁移——请运行 "
                    "scripts/migrate_json_to_pg.py 搬迁，否则这批数据滞留旧文件（降级必有痕）"
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"本地文件 store 也不可用（{e}），降级内存 store：数据重启即丢！")

        # 3) 内存兜底：最后一道，明确标注会丢
        _store = candidate if candidate is not None else MemoryStore()
        logger.info(f"存储后端就绪: {type(_store).__name__}")
    return _store


def reset_store_for_tests() -> None:
    """清空单例（测试隔离用）。"""
    global _store
    _store = None
