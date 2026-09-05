#!/bin/bash
# 创业者工作台 — 启动脚本
# 使用 fangan1 的 venv Python（shangzhu 的 .venv 软链到 WPS Python 缺 uvicorn）
# 端口: 8081
# 用法: ./start.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# 优先使用项目自带 .venv（uv sync 重建过，含全部依赖）；
# 若缺失（如旧机器上 .venv 是软链到 WPS Python 缺 uvicorn），回退到 fangan1 的 venv。
VENV_PY="$SCRIPT_DIR/.venv/bin/python3"
if [ ! -x "$VENV_PY" ]; then
    VENV_PY="/Users/newmacbook/Desktop/pangdekuan/fangan1/.venv/bin/python3"
fi
LOG="$SCRIPT_DIR/logs/shangzhu.log"
PORT="${PORT:-8081}"

mkdir -p logs output

if [ ! -x "$VENV_PY" ]; then
    echo "[start] 错误：venv Python 不存在: $VENV_PY" >&2
    exit 1
fi

# 快速导入冒烟
if ! "$VENV_PY" -c "from web_server import app; assert app is not None" 2>/tmp/shangzhu_start_import.err; then
    echo "[start] 错误：web_server 导入失败，详见 /tmp/shangzhu_start_import.err"
    cat /tmp/shangzhu_start_import.err >&2 || true
    exit 1
fi

echo "[shangzhu] 启动中... (端口 $PORT, 日志: $LOG)"
exec "$VENV_PY" -c "
import uvicorn
from web_server import app
uvicorn.run(app, host='127.0.0.1', port=$PORT, log_level='warning')
" >> "$LOG" 2>&1
