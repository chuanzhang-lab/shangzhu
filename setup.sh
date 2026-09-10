#!/usr/bin/env bash
# 创业者商业建模工作台 — 一键初始化脚本
#
# 设计目标：无需关心当前目录，从任意位置直接跑都行。
#   完整克隆： git clone <repo> && cd <repo> && bash setup.sh
#   一行验证： gh repo clone chuanzhang-lab/claude && cd claude && bash setup.sh
#
# 幂等：可重复执行，不会覆盖已有配置、不会重建已有 .venv 内容。
#
# 用法：
#   bash setup.sh            # 安装依赖 + 生成配置 + 跑测试（推荐首次）
#   bash setup.sh --start    # 上述全部 + 结束后直接启动服务
#   bash setup.sh --no-test  # 跳过测试（只做环境准备）
set -euo pipefail

# ── 步骤 0：切到脚本所在目录（解决"从 ~ 跑找不到文件"问题）────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1
echo "[setup] 项目目录: $SCRIPT_DIR"

AUTO_START=0
RUN_TEST=1
for arg in "$@"; do
  case "$arg" in
    --start)   AUTO_START=1 ;;
    --no-test) RUN_TEST=0 ;;
    -h|--help)
      sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "[setup] 未知参数: $arg（可用: --start / --no-test）" >&2; exit 1 ;;
  esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '    ✅ %s\n' "$1"; }
warn() { printf '    ⚠️  %s\n' "$1"; }
die()  { printf '\n\033[31m[setup] 失败: %s\033[0m\n' "$1" >&2; exit 1; }

# ── 步骤 1：前置检查（python3 / uv）────────────────────────────────────────
say "步骤 1/6 前置检查"

command -v python3 >/dev/null 2>&1 || die "未找到 python3，请先安装 Python 3.12+"
ok "python3: $(python3 --version 2>&1)"

if ! command -v uv >/dev/null 2>&1; then
  warn "未找到 uv，尝试自动安装（https://astral.sh/uv）"
  if command -v brew >/dev/null 2>&1; then
    brew install uv || die "brew install uv 失败，请手动安装后重跑"
  elif command -v curl >/dev/null 2>&1; then
    # 注意：这里刻意不用 curl | sh 的管道写法，先下载再执行，便于校验与中断
    curl -fsSL https://astral.sh/uv/install.sh -o /tmp/uv_install.sh \
      || die "下载 uv 安装脚本失败"
    sh /tmp/uv_install.sh || die "uv 安装失败"
    rm -f /tmp/uv_install.sh
  else
    die "缺少 curl 与 brew，无法自动安装 uv，请手动安装后重跑"
  fi
fi
ok "uv: $(uv --version 2>&1 | head -1)"

# ── 步骤 2：安装依赖（uv sync → .venv）─────────────────────────────────────
say "步骤 2/6 安装依赖（uv sync）"
if [ -f "uv.lock" ]; then
  uv sync --frozen || uv sync
else
  uv sync
fi
ok "依赖已就绪: $SCRIPT_DIR/.venv"

VENV_PY="$SCRIPT_DIR/.venv/bin/python3"
[ -x "$VENV_PY" ] || die ".venv 未生成 python3: $VENV_PY"

# ── 步骤 3：生成 LLM 配置（该文件被 gitignore，新克隆必然缺失）─────────────
say "步骤 3/6 生成配置文件"
mkdir -p config

if [ -f "config/agent_llm_config.json" ]; then
  ok "config/agent_llm_config.json 已存在，保留原值"
else
  cat > config/agent_llm_config.json <<'JSON'
{
  "config": {
    "model": "",
    "base_url": "",
    "api_key": "",
    "temperature": 0.3,
    "top_p": 0.9,
    "max_completion_tokens": 10000,
    "timeout": 60
  }
}
JSON
  chmod 600 config/agent_llm_config.json
  ok "已生成 config/agent_llm_config.json（占位，api_key 留空）"
  warn "未配置 api_key 时：规则引擎照常工作，AI 解读自动跳过"
fi

if [ -f "config/storage.json" ]; then
  ok "config/storage.json 已存在，保留原值"
elif [ -f "config/storage.json.example" ]; then
  cp config/storage.json.example config/storage.json
  chmod 600 config/storage.json
  ok "已从 example 生成 config/storage.json"
fi

# ── 步骤 4：导入冒烟（提前暴露依赖问题）────────────────────────────────────
say "步骤 4/6 导入冒烟"
if "$VENV_PY" -c "from web_server import app; assert app is not None" 2>/tmp/shangzhu_setup.err; then
  ok "web_server 导入正常"
else
  cat /tmp/shangzhu_setup.err >&2 || true
  die "web_server 导入失败（依赖可能不完整），详见上方错误"
fi

# ── 步骤 5：初始化数据库（可选：PG 不可用时跳过，服务会自动降级内存存储）────
say "步骤 5/6 初始化数据库（可选）"
if command -v psql >/dev/null 2>&1 && pg_isready -q 2>/dev/null; then
  if "$VENV_PY" scripts/init_db.py 2>/tmp/shangzhu_db.err; then
    ok "PostgreSQL 已初始化"
  else
    warn "数据库初始化失败（不影响启动，将降级为内存存储）"
    warn "详情: $(tail -2 /tmp/shangzhu_db.err 2>/dev/null)"
  fi
else
  warn "未检测到可用 PostgreSQL，跳过建库"
  warn "服务仍可运行（会话不持久化，重启即丢）；需要持久化请先安装并启动 PG"
fi

# ── 步骤 6：跑测试 ─────────────────────────────────────────────────────────
if [ "$RUN_TEST" -eq 1 ]; then
  say "步骤 6/6 运行测试"
  if [ -f "tests/run_all.py" ]; then
    "$VENV_PY" tests/run_all.py || die "测试未通过"
  else
    "$VENV_PY" -m pytest tests/ -q || die "测试未通过"
  fi
  ok "测试通过"
else
  say "步骤 6/6 跳过测试（--no-test）"
fi

# ── 收尾 ───────────────────────────────────────────────────────────────────
cat <<TIP

${SCRIPT_DIR} 初始化完成 ✅

  启动服务：    ./start.sh
  健康检查：    curl http://127.0.0.1:8081/health
  配置模型：    编辑 config/agent_llm_config.json 填入 model/base_url/api_key
                （或启动后在网页右上角的设置入口里填写）

TIP

if [ "$AUTO_START" -eq 1 ]; then
  say "自动启动服务（--start）"
  exec ./start.sh
fi
