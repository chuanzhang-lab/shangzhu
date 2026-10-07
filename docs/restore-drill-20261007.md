# 恢复演练记录 —— PostgreSQL 备份可恢复性实测

> 日期：2026-10-07 ｜ 提交基线：`main` @ d004678 + 存储加固批 1–3
> 结论：**备份可恢复，行数与生产库完全一致；演练全程未触碰生产库。**

## 1. 为什么补这份记录

存储加固审查（2026-10-07）的 P0 之一（X1）：此前只有 `scripts/backup_db.sh`
（`pg_dump | gzip`），没有恢复脚本、没有恢复步骤、产物从不校验。也就是说
**「备份过」只是纸面承诺**——真出事时没演练过、没验证过，无法回答
「这份备份能不能恢复」这个问题。

按仓库既有惯例（每起事故一条护栏，且护栏必须负向实测），恢复能力也要能被
**一条命令证伪**：`make drill`。

## 2. 环境

| 项 | 值 |
|---|---|
| 平台 | macOS（darwin 25.6.0, arm64） |
| PostgreSQL | 16.14 (Homebrew)，`localhost:5432` |
| 库 | `shangzhu`（业务库） |
| 连接串来源 | `src/storage/dburl.py` 单源（此处为内置默认，未设 `PGDATABASE_URL`） |
| 客户端 | `pg_dump` / `pg_restore` / `psql` / `createdb` / `dropdb`（Homebrew path） |

## 3. 步骤与真实输出

### 3.1 备份（`make backup`）

```
[backup] 备份 localhost:5432/shangzhu → /Users/newmacbook/Desktop/shangzhu/backups/shangzhu_20261007_103224.dump
[backup] 校验通过（pg_restore --list 可列出目录）
[backup] 完成 — 148K、权限 600、连接串 postgresql://***:***@localhost:5432/shangzhu
```

产物权限实测：

```
drwx------  backups/                              （700）
-rw-------  shangzhu_20261007_103224.dump          （600，147524 字节）
```

要点：连接串来自单源（与 store 用的完全同一个），库名不再写死；写完立刻用
`pg_restore --list` 校验，列不出目录就报错退出——不可验证的备份不算备份。

### 3.2 演练（`make drill`）

```
[restore] 产物校验通过: shangzhu_20261007_103224.dump
[restore] 创建库 shangzhu_drill_20261007_103259 ...
[restore] 恢复 .../shangzhu_20261007_103224.dump → shangzhu_drill_20261007_103259 ...
[restore] 恢复完成。行数核对：648 任务 / 1471 消息
[restore] 演练结论：备份可恢复（库 shangzhu_drill_20261007_103259 上表结构与数据均就位）
[restore] 清理临时库 shangzhu_drill_20261007_103259 ...
[restore] 演练结束（临时库已删，生产库 shangzhu 全程未触碰）
```

### 3.3 行数核对与残留检查

| 检查项 | 结果 |
|---|---|
| 生产库（演练前） | 648 任务 / 1471 消息 |
| 恢复库（临时） | 648 任务 / 1471 消息 |
| 是否一致 | **一致** ✅ |
| 演练后生产库 | 648 任务 / 1471 消息（未被触碰）✅ |
| `shangzhu_drill*` 临时库残留 | 0 个 ✅ |

## 4. 本次演练发现并修掉的问题

| 问题 | 形态 | 处置 |
|---|---|---|
| `restore_db.sh` 语法错误 | 双引号内用 `\` 续行会吞掉引号边界 → `syntax error near unexpected token '('`，演练第一次直接失败 | SQL 先赋变量再传 `-c`（脚本内已留注释，护栏 test_backup_restore_guard 覆盖四档） |
| 备份只写不校验 | 产物损坏也能"成功"退出（X1） | 改为 `-Fc` + 写完即 `pg_restore --list` 校验 |
| 备份错库风险 | 旧脚本 `$(whoami)` + 写死 `shangzhu`，改过 `PGDATABASE_URL` 的用户会备份到另一个库（L4） | 连接串/库名统一取自 `storage/dburl.py` |
| 恢复后无核对 | 恢复"完成"与否只能靠 `pg_restore` 退出码 | `verify_counts()` 打印 `任务 / 消息` 行数，演练据此比对 |

## 5. 运维口径（写进 README 与 Makefile）

```bash
make doctor         # 环境体检：PG 五层分辨 + 可粘贴的修复命令
make backup         # -Fc 备份到 backups/（写完即校验，保留最近 7 份）
make restore-check  # 校验最新备份可读
make drill          # 恢复演练：临时库 + 行数核对 + 自动清理（不碰生产库）
make restore        # 从最新备份恢复到一个新库（非破坏性切换）
./scripts/restore_db.sh --force   # 覆盖当前业务库：需交互输入 yes 才会执行
```

**规矩**：任何改动存储层的提交之前跑一次 `make drill`；每季度至少一次。

## 6. 明确的能力边界（不假装有）

- **没有 PITR**：本方案只有 `pg_dump` 快照，**不能**恢复到任意时间点（无 WAL 归档）。
  可恢复粒度 = 最近一次备份（默认保留 7 份）。要做 PITR 需另配 WAL 归档，本轮不做。
- **备份未加密**：产物是标准 PG 自定义格式，`600` 权限 + `backups/` 已在 `.gitignore`；
  但若被拷到网盘/共享目录，内容等同明文（含全部经营数据与对话历史）。
- **演练只证明"能恢复"**，不证明"恢复后业务口径全对"（后者由测试套与
  `scripts/migrate_json_to_pg.py` 的幂等迁移共同保证）。
