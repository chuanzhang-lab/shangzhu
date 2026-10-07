# 数据库使用说明（PostgreSQL）

> 面向日常使用：装机、体检、备份、恢复、降级、迁回，以及怎么知道自己该备份了。
> 完整背景与方向决策见 `docs/decision-storage-pg-20261007.md`；
> 演练记录见 `docs/restore-drill-20261007.md`。

本仓是**双副本**仓库（CN `shangzhu` / EN `shangzhu-en`）。存储层是**显式豁免层**：
CN 用 PostgreSQL，EN 用 SQLite——这是有意分叉，不是漂移。

---

## 1. 数据落在哪（三级口径，务必分清）

默认 `postgresql://<系统用户名>@localhost:5432/shangzhu`；可用 `PGDATABASE_URL`
或 `config/storage.json` 的 `db_url` 覆盖。优先级：**env → 配置文件 → 内置默认**
（唯一解析出处：`src/storage/dburl.py`，脚本一律复用它，不自己拼）。

| 档 | 触发 | 数据落在哪 | 重启 | 怎么迁回 |
|---|---|---|---|---|
| ① PG 可用 | 默认 | PostgreSQL | 不丢 | — |
| ② PG 不可用 | 连不上 / 没建库 | `data/local_store.json` | 不丢 | PG 恢复后 `scripts/migrate_json_to_pg.py`（默认 dry-run） |
| ③ 文件也写不了 | 磁盘 / 权限问题 | 内存 | **丢** | 无（日志 ERROR + 页面红色横幅） |

② 不是丢数据，是**分流**。想知道当前在哪一档：看 `/health` 的 `store_*` 字段，
或页面顶部横幅（橙色=文件、红色=内存）。

**档位开关**：`STORE_BACKEND=auto|pg|file|memory`（env 或 `config/storage.json` 的 `backend`）。
- `auto`（默认）：上表的降级链。
- `pg`：**只要 PG、拒绝降级**——连不上就明确报错 + 启动前体检，适合"要么 PG 要么告诉我"。
- `file` / `memory`：显式选择，页面会提示当前模式。

---

## 2. 每天/每周要跑的三条命令

```bash
make doctor          # 环境体检：六层分辨，每层给可粘贴的修复命令
make backup          # 备份到 backups/（-Fc，写完即 pg_restore --list 校验，保留最近 7 份）
make drill           # 恢复演练：临时库 → 行数核对 → 自动清理（全程不碰生产库）
```

其他：

```bash
make restore-check   # 校验最新备份可读
make restore         # 恢复到**新库**（非破坏性）；覆盖生产库用 scripts/restore_db.sh --force
.venv/bin/python3 src/storage/backup_status.py      # 只看备份新鲜度（不触发备份）
.venv/bin/python3 scripts/backfill_task_turn.py     # tasks.turn 存量回填（幂等，默认预演）
```

---

## 3. 备份新鲜度（别把「有能力备份」当成「没忘记备份」）

`make backup` 全自动且会自检产物，但**它得有人记得跑**。为此加了可读出口：

- `/health` 三个字段：`backup_stale`（是否过期）、`backup_age_days`（距今天数）、`backup_latest`（最新文件名）。
- `doctor.py` 的 **L6 备份新鲜度**层：⚠️ 表示过期（**非阻塞**——不拦启动，但要看）。
- 阈值 `BACKUP_MAX_AGE_DAYS`，默认 7 天（与 `backup_db.sh` 保留 7 份对齐）。零备份也判 stale。

### 定时自动备份（可选，强烈建议）

改数据前想不起来跑备份，就交给调度器：

**macOS（launchd）** — 存为 `~/Library/LaunchAgents/cn.shangzhu.backup.plist`，每天 21:00 跑一次：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>cn.shangzhu.backup</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>-lc</string>
    <string>cd /Users/newmacbook/Desktop/shangzhu &amp;&amp; ./scripts/backup_db.sh &gt;&gt; logs/backup.log 2&gt;&amp;1</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
  <key>RunAtLoad</key><false/>
</dict></plist>
```

```bash
launchctl load -w ~/Library/LaunchAgents/cn.shangzhu.backup.plist
launchctl list | grep shangzhu      # 确认已加载
```

**Linux（cron）** — `crontab -e`：

```cron
0 21 * * * cd /path/to/shangzhu && ./scripts/backup_db.sh >> logs/backup.log 2>&1
```

> 备份目录 `backups/` 与降级目录 `data/` **都不入库**，产物权限 `600`。

---

## 4. `tasks.turn` 是什么（以及它曾经是死列）

`tasks.turn` 记录该任务进行到第几轮；`messages.turn` 记录每条消息属于第几轮。

2026-10-08 前，两列都是**只定义、从不写**的死列（同类问题）：

| 列 | 修复前实测 | 真值其实在哪 | 现在 |
|---|---|---|---|
| `tasks.turn` | 650 行恒为 0 | `messages.turn` | 三 store 统一推进；PG 侧 `GREATEST` 保证**单调不回退**；存量回填 131 行 |
| `tasks.industry` | 651 行全 NULL | `params->>'industry'` | 从 params 同步落库，**只增不抹**（params 没带行业时不覆盖已定值）；存量回填 30 行 |

两列合用一个幂等脚本（默认预演，改数据前先 `make backup`）：

```bash
.venv/bin/python3 scripts/backfill_task_columns.py            # 预演
.venv/bin/python3 scripts/backfill_task_columns.py --apply     # 写入（再跑应为 0 行）
```

---

## 5. 装机（第一次）

```bash
brew install postgresql@16 && brew services start postgresql@16   # macOS
# Debian/Ubuntu: sudo apt install postgresql && sudo systemctl start postgresql
```

装完**先验证再启动**：

```bash
.venv/bin/python3 scripts/doctor.py      # 六层 ✅/⚠️/❌，❌ 行直接给要跑的命令
.venv/bin/python3 scripts/init_db.py     # 幂等建库建表（服务首次连接也会自动建表）
```

不想装本机服务：`export PGDATABASE_URL=postgresql://<user>@<host>:5432/<db>` 指向已有 PG。

---

## 6. 排障表

| 症状 | 原因 | 处置 |
|---|---|---|
| `connection refused` / 页面橙色横幅 | 服务没起（含重启后 `brew services` 未自启） | `brew services start postgresql@16`，用 `pg_isready` 复查 |
| `database "shangzhu" does not exist` | 还没建库 | `.venv/bin/python3 scripts/init_db.py` |
| `role "xxx" does not exist` | 数据库角色不存在 | `createuser -s $(whoami)` 后重跑 `init_db.py` |
| `password authentication failed` | 认证方式不是 peer | 用带凭据的 `PGDATABASE_URL`，或 `~/.pgpass`（`chmod 600`）。**密码不要进仓库文件** |
| 页面红色横幅 | 已降级到内存（文件也写不了） | 查磁盘与 `data/` 权限；此档重启即丢 |
| `/health` `backup_stale=true` | 超过 7 天没备份（或零备份） | `make backup`；长期用第 3 节的定时 |
| 降级期的数据想迁回 PG | —— | `.venv/bin/python3 scripts/migrate_json_to_pg.py`（先 dry-run） |
| 要覆盖生产库恢复 | —— | `make drill` 先演练；确认后 `./scripts/restore_db.sh --force`（需交互输 `yes`） |

---

## 7. 一分钟自检清单

```bash
pg_isready                                            # 服务在
.venv/bin/python3 scripts/doctor.py                   # 六层绿（L6 ⚠️ 就去备份）
.venv/bin/python3 src/storage/backup_status.py        # 备份没过期
curl -s --noproxy '*' localhost:8081/health \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['store_backend'], d['store_degraded'], d['backup_stale'], d['store_write_failures'])"
# 期望： PostgresStore False False 0
```
