#!/usr/bin/env bash
# 备份 PostgreSQL 数据库（pg_dump -Fc 自定义格式：可校验、可选择性恢复）
#
# 用法: ./scripts/backup_db.sh
#
# 连接串取自 src/storage/dburl.py **单源**（PGDATABASE_URL → config/storage.json →
# 默认），不再自己拼 $(whoami) + 写死 shangzhu。背景（2026-10-07 加固 L4）：
# 用户改过 PGDATABASE_URL 后，旧脚本备份的是另一个库（或直接失败）——
# 「备份过」与「备份的是你正在用的库」是两件事。
#
# 成品: backups/<库名>_<日期>.dump（0600，保留最近 7 份）
#   · 用 -Fc 而非 `| gzip`：可 pg_restore --list 校验、可选择性恢复单表；
#   · 写完立刻校验，列不出目录就报错退出（加固 X1：备份必须可验证）。
# 恢复见 scripts/restore_db.sh（--check / --into-db / --force）。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PY="${PY:-$PROJECT_ROOT/.venv/bin/python3}"
[ -x "$PY" ] || PY="$(command -v python3)"

DBURL_PY="$PROJECT_ROOT/src/storage/dburl.py"
DB_NAME="$("$PY" "$DBURL_PY" --dbname)"
TARGET="$("$PY" "$DBURL_PY" --target)"
URL="$("$PY" "$DBURL_PY")"
SAFE="$("$PY" "$DBURL_PY" --safe)"

BACKUP_DIR="${PROJECT_ROOT}/backups"
DATE_TAG="$(date +%Y%m%d_%H%M%S)"
OUT_FILE="${BACKUP_DIR}/${DB_NAME}_${DATE_TAG}.dump"

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "[backup] 未找到 pg_dump（PostgreSQL 客户端）" >&2
  echo "[backup]   macOS : brew install postgresql@16" >&2
  echo "[backup]   Debian: sudo apt install postgresql-client" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR" 2>/dev/null || true

# 前置：服务可达（快速失败——别让 pg_dump 卡几十秒才报错）
if command -v pg_isready >/dev/null 2>&1; then
  HOST="$("$PY" "$DBURL_PY" --host)"
  PORT="$("$PY" "$DBURL_PY" --port)"
  if ! pg_isready -q -h "$HOST" -p "$PORT"; then
    echo "[backup] PostgreSQL 不可达（$TARGET）——先启动服务再备份。" >&2
    echo "[backup] 环境体检：" >&2
    "$PY" "$PROJECT_ROOT/scripts/doctor.py" >&2 || true
    exit 1
  fi
fi

echo "[backup] 备份 $TARGET → $OUT_FILE"
pg_dump --format=custom --dbname="$URL" > "$OUT_FILE"
chmod 600 "$OUT_FILE"

# 校验：能列出目录才算「可恢复的备份」
if command -v pg_restore >/dev/null 2>&1; then
  if pg_restore --list "$OUT_FILE" >/dev/null 2>&1; then
    echo "[backup] 校验通过（pg_restore --list 可列出目录）"
  else
    echo "[backup] 校验失败：产物不可读，请勿依赖此备份（文件保留供排查）：$OUT_FILE" >&2
    exit 1
  fi
else
  echo "[backup] 警告：未找到 pg_restore，跳过产物校验" >&2
fi

echo "[backup] 完成 — $(du -h "$OUT_FILE" | cut -f1)、权限 600、连接串 $SAFE"

# 保留最近 7 份（while-read 形式：BSD/GNU 都稳，不依赖 xargs -r）
ls -t "$BACKUP_DIR"/*.dump 2>/dev/null | tail -n +8 | while read -r f; do
  rm -f "$f"
  echo "[backup] 清理旧备份: $(basename "$f")"
done
