#!/bin/bash
# 创业者工作台 — 启动脚本
# 自动使用 .venv 中的 Python，确保依赖正确
# 用法: ./start.sh [-p PORT] [--host HOST]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# 若 .venv 不存在，先尝试用 uv 初始化
if [ ! -d ".venv" ]; then
    echo "[start] .venv 不存在，尝试初始化..."
    if ! command -v uv >/dev/null 2>&1; then
        echo "[start] 错误：未安装 uv，请先安装 uv (https://docs.astral.sh/uv/)"
        exit 1
    fi
    uv sync
fi

PY="./.venv/bin/python"
if [ ! -x "$PY" ]; then
    # 兼容部分环境只有 python3
    if [ -x "./.venv/bin/python3" ]; then
        PY="./.venv/bin/python3"
    else
        echo "[start] 错误：.venv 中未找到可执行的 python"
        exit 1
    fi
fi

# 启动前预检：关键文件与最小导入
if [ ! -f "web_server.py" ]; then
    echo "[start] 错误：缺少 web_server.py"
    exit 1
fi
if [ ! -f "config/agent_llm_config.json" ]; then
    echo "[start] 错误：缺少 config/agent_llm_config.json"
    exit 1
fi

mkdir -p logs output

if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
    echo "[start] 提示：未设置 DEEPSEEK_API_KEY，Engine Steward 将静默跳过，规则引擎照常工作"
fi

# 快速导入冒烟（失败则不启动，避免半残服务）
if ! "$PY" -c "import web_server; assert web_server.app is not None" 2>/tmp/shangzhu_start_import.err; then
    echo "[start] 错误：web_server 导入失败，详见 /tmp/shangzhu_start_import.err"
    cat /tmp/shangzhu_start_import.err >&2 || true
    exit 1
fi

exec "$PY" web_server.py "$@"
