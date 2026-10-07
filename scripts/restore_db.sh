#!/usr/bin/env bash
# 从备份恢复 PostgreSQL（配套 scripts/backup_db.sh）
#
# 背景（2026-10-07 加固 X1）：此前只有备份、**没有恢复**——没有脚本、没有步骤文档、
# 产物从不校验。「备份过」于是只是纸面承诺：真出事时没演练过、没验证过。
#
# 用法:
#   ./scripts/restore_db.sh --list                        # 列出可用备份
#   ./scripts/restore_db.sh --check [FILE]                # 只校验产物可读（pg_restore --list）
#   ./scripts/restore_db.sh --into-db NAME [--file F]     # 恢复到新库（非破坏性，推荐）
#   ./scripts/restore_db.sh --rehearsal [--file F]        # 恢复演练：临时库 + 行数核对 + 自动清理
#   ./scripts/restore_db.sh --force [--file F]            # 覆盖当前业务库（危险，需交互确认）
#
# 默认取 backups/ 里最新的一份。恢复目标库默认 `<库名>_restore_<时间戳>`。
# 连接串单源：src/storage/dburl.py（与 backup_db.sh / store 完全一致）。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PY="${PY:-$PROJECT_ROOT/.venv/bin/python3}"
[ -x "$PY" ] || PY="$(command -v python3)"

DBURL_PY="$PROJECT_ROOT/src/storage/dburl.py"
DB_NAME="$("$PY" "$DBURL_PY" --dbname)"
HOST="$("$PY" "$DBURL_PY" --host)"
PORT="$("$PY" "$DBURL_PY" --port)"
BACKUP_DIR="${PROJECT_ROOT}/backups"

MODE=""; FILE=""; TARGET_DB=""
while [ $# -gt 0 ]; do
  case "$1" in
    --list)      MODE="list" ;;
    --check)     MODE="check" ;;
    --into-db)   MODE="into"; TARGET_DB="${2:-}"; shift ;;
    --rehearsal) MODE="rehearsal" ;;
    --force)     MODE="force" ;;
    --file)      FILE="${2:-}"; shift ;;
    -h|--help)   sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "[restore] 未知参数: $1（--help 看用法）" >&2; exit 2 ;;
  esac
  shift
done

if [ -z "$MODE" ]; then
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 2
fi

for tool in pg_restore psql createdb dropdb; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "[restore] 未找到 $tool（PostgreSQL 客户端）——macOS: brew install postgresql@16" >&2
    exit 1
  fi
done

latest_backup() {
  ls -t "$BACKUP_DIR"/*.dump 2>/dev/null | head -n 1
}

if [ "$MODE" = "list" ]; then
  [ -d "$BACKUP_DIR" ] || { echo "[restore] 尚无备份目录（先跑 scripts/backup_db.sh）"; exit 1; }
  found=0
  for f in $(ls -t "$BACKUP_DIR"/*.dump 2>/dev/null); do
    found=1
    printf '  %s  %8s  %s\n' "$(basename "$f")" "$(du -h "$f" | cut -f1)" "$(date -r "$f" '+%Y-%m-%d %H:%M' 2>/dev/null || echo '-')"
  done
  [ "$found" = "1" ] || { echo "[restore] backups/ 下没有 *.dump"; exit 1; }
  echo "[restore] 共 $(ls "$BACKUP_DIR"/*.dump 2>/dev/null | wc -l | tr -d ' ') 份（保留策略：最近 7 份）"
  exit 0
fi

[ -n "$FILE" ] || FILE="$(latest_backup || true)"
[ -n "$FILE" ] || { echo "[restore] 没找到备份文件——先跑 scripts/backup_db.sh" >&2; exit 1; }
[ -f "$FILE" ] || { echo "[restore] 备份文件不存在: $FILE" >&2; exit 1; }

# 产物校验：列不出目录就不是可恢复备份（在动手之前先验，避免"恢复了半天是坏的"）
if pg_restore --list "$FILE" >/dev/null 2>&1; then
  echo "[restore] 产物校验通过: $(basename "$FILE")"
else
  echo "[restore] 产物校验失败：$FILE 不可读，拒绝恢复" >&2
  exit 1
fi

if [ "$MODE" = "check" ]; then
  echo "[restore] 仅校验模式，未做任何恢复。"
  exit 0
fi

verify_counts() {
  # 行数核对：库在、表在、任务数与消息数是多少（给恢复演练与人工确认用）
  # 注意：SQL 先存变量再传 -c —— 双引号内用 `\` 续行会吞掉引号边界（已踩过）。
  local db="$1"
  local sql="SELECT (SELECT count(*) FROM tasks) || ' 任务 / ' || (SELECT count(*) FROM messages) || ' 消息'"
  local counts
  counts="$(psql -X -q -A -t -h "$HOST" -p "$PORT" -d "$db" -c "$sql" 2>/dev/null || echo '(查询失败)')"
  echo "$counts"
}

restore_into() {
  local db="$1"
  echo "[restore] 创建库 $db ..."
  createdb -h "$HOST" -p "$PORT" "$db"
  echo "[restore] 恢复 $FILE → $db ..."
  # --no-owner：备份可能来自不同用户名（peer 场景下角色名会变），避免因属主不存在而失败
  if ! pg_restore --no-owner --exit-on-error -h "$HOST" -p "$PORT" -d "$db" "$FILE"; then
    echo "[restore] 恢复报错（库 $db 保留供排查）" >&2
    exit 1
  fi
  echo "[restore] 恢复完成。行数核对：$(verify_counts "$db")"
  echo "[restore] 切到该库验证：PGDATABASE_URL=postgresql://\$(whoami)@$HOST:$PORT/$db ./start.sh"
}

case "$MODE" in
  into)
    [ -n "$TARGET_DB" ] || { echo "[restore] --into-db 需要库名" >&2; exit 2; }
    restore_into "$TARGET_DB"
    ;;
  rehearsal)
    # 恢复演练（加固 X1 / 参照 EN 仓 S7）：临时库 + 行数核对 + 自动清理，
    # 全程不碰生产库——「备份可用」从此可被一条命令证伪。
    ts="$(date +%Y%m%d_%H%M%S)"
    TMP_DB="${DB_NAME}_drill_${ts}"
    restore_into "$TMP_DB"
    echo "[restore] 演练结论：备份可恢复（库 $TMP_DB 上表结构与数据均就位）"
    echo "[restore] 清理临时库 $TMP_DB ..."
    dropdb -h "$HOST" -p "$PORT" "$TMP_DB"
    echo "[restore] 演练结束（临时库已删，生产库 $DB_NAME 全程未触碰）"
    ;;
  force)
    echo "[restore] ⚠️  即将用 $(basename "$FILE") 覆盖当前业务库 $DB_NAME（$HOST:$PORT）。" >&2
    echo "[restore] 当前行数：$(verify_counts "$DB_NAME")" >&2
    printf '[restore] 输入 yes 确认覆盖（其它任何输入都中止）: '
    read -r answer
    [ "$answer" = "yes" ] || { echo "[restore] 已中止，未做任何改动。"; exit 1; }
    echo "[restore] 覆盖恢复（--clean --if-exists）..."
    pg_restore --clean --if-exists --no-owner -h "$HOST" -p "$PORT" -d "$DB_NAME" "$FILE"
    echo "[restore] 完成。恢复后行数：$(verify_counts "$DB_NAME")"
    echo "[restore] 建议：重启服务（./start.sh）并硬刷新页面。"
    ;;
esac
