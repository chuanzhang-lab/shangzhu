#!/usr/bin/env bash
# 备份 PostgreSQL 数据库（pg_dump + gzip + 日期命名）
# 用法: ./scripts/backup_db.sh [数据库名]
# 默认数据库名: shangzhu
# 输出目录: 项目根下的 backups/

set -euo pipefail

DB_NAME="${1:-shangzhu}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_ROOT}/backups"
DATE_TAG="$(date +%Y%m%d_%H%M%S)"
OUT_FILE="${BACKUP_DIR}/${DB_NAME}_${DATE_TAG}.sql.gz"

mkdir -p "$BACKUP_DIR"

# 连接用户：优先 PGUSER，否则当前系统用户（免密 peer 连接，不绑定机器）
DB_USER="${PGUSER:-$(whoami)}"

echo "[backup] Dumping ${DB_NAME} → ${OUT_FILE}"
pg_dump "postgresql://${DB_USER}@localhost:5432/${DB_NAME}" | gzip > "$OUT_FILE"

echo "[backup] Done — $(du -h "$OUT_FILE" | cut -f1)"

# 保留最近 7 份备份，删除更早的
cd "$BACKUP_DIR"
ls -t ./*.sql.gz 2>/dev/null | tail -n +8 | xargs -r rm -f
echo "[backup] Cleaned old backups (last 7 kept)"
