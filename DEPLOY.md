# 托管部署规程（sites 发布）

线上实例：见 README 顶部链接（中文版）。
机房：腾讯云 CLB 北京节点。**国内直连无需翻墙**——中文版面向国内店主，这个节点反而是最优解。

## 发布前必做：两道安全闸

### 1. 移出密钥（必做，否则会连密钥一起上传）
部署是**目录原样上传**，`.gitignore` 管不到它。`config/agent_llm_config.json`
被 gitignore 覆盖，但 **`agent_llm_config.json.bak` 不在忽略列表里**——同样带密钥，最容易漏。

```bash
mkdir -p ../_keys_shangzhu_zh
mv config/agent_llm_config.json config/agent_llm_config.json.bak ../_keys_shangzhu_zh/
# 发布完成后再移回来，本地开发照常用
mv ../_keys_shangzhu_zh/agent_llm_config.json* config/
```

漏做的后果：`/health` 会显示 `llm_configured: true`，任何人点「AI 解读」都在烧你的 key。
**注意**：沙箱会复用同一实例，只删本地文件后重发**不够**（旧文件还在服务端），
必须用「无密钥占位配置覆盖」再发一次，直到 `/health` 报 `llm_configured: false`。

### 2. 开内存档（公开实例必做）
公开实例不能把陌生人的经营数字（租金、客流、利润）写进服务端磁盘。
本仓与英文版不同：**已有 `STORE_BACKEND` 显式档位**（`auto` / `pg` / `file` / `memory`，
见 `src/storage/dburl.py`），所以公开实例直接设 `STORE_BACKEND=memory` 即可，
不需要改代码。该档会打日志明示「数据只存内存，重启即丢」，不静默降级。

> 持久化首选本是 PostgreSQL（`psycopg`），沙箱里连不上 PG——但 `memory` 档
> 在 PG 之前就返回，不触发连接；`psycopg` 仍装（延迟导入，装而不连）。

## 发布命令（workbuddy_sites_deploy）

```json
{
  "directory": "/Users/newmacbook/Desktop/shangzhu",
  "language": "python",
  "port": 8081,
  "installCmd": "pip install --ignore-requires-python -r requirements-deploy.txt",
  "startCmd": "sh -c 'STORE_BACKEND=memory WEB_CONCURRENCY=1 exec python3 -m uvicorn web_server:app --host 0.0.0.0 --port \\\"$PORT\\\"'",
  "domainPrefix": "shangzhu",
  "appName": "创业者测算工作台"
}
```

## 四个必须记住的坑

1. **沙箱 Python 是 3.11**，本项目 `requires-python = ">=3.12"` → `pip install -e .` 会被拒，
   必须 `--ignore-requires-python`（代码已确认不含 3.12 专属语法）。
2. **不能让 pip 自由解析**：会装出与 `langchain==1.0.3` 不匹配的 langgraph，
   import 期崩在 `from langgraph.prebuilt import ToolRuntime`。
   所以装的是 `requirements-deploy.txt`——由 `uv export --frozen --no-emit-project --no-hashes`
   从 `uv.lock` 导出的精确版本。**lock 变了必须重新导出**：
   ```bash
   uv lock && uv export --frozen --no-emit-project --no-hashes -o /tmp/r.txt
   ```
3. **`startCmd` 里的 `$PORT` 不会被展开**（报 `Option '--port' requires an argument`），
   必须包一层 `sh -c '... --port "$PORT"'`。
4. **pre-commit 三件套会跑全量 pytest**（compile + eslint + pytest，约 70s）。
   本机直接跑 pytest 会报一批 `PermissionError: EEXIST mkdir /private/tmp/pytest-of-*`
   ——那是 WorkBuddy 沙箱 shim 拦临时目录，**与代码无关**，加
   `--basetemp=/tmp/pt` 指向全新目录即消失。别被它误导去改代码。

## 为什么有 requirements-deploy.txt

开发依赖走 `uv` + `pyproject.toml`（无 `requirements.txt`，`.venv` 不入库）。
托管沙箱没有 uv，只能 pip 装，所以需要一份从 lock 导出的固定版本清单。
**它不是依赖的第二出处**——唯一出处仍是 `pyproject.toml` + `uv.lock`，此文件是派生产物。

## 发布后自检

```bash
curl --noproxy '*' <链接>/health
curl --noproxy '*' "<链接>/health?detail=1"
```

必须同时满足：
- `llm_configured: false`（密钥没上去）
- `store_backend: MemoryStore`（数据不落盘）
- `version` 与本地 `pyproject.toml` 一致

再跑一次真实对话（带 `X-Requested-With: XMLHttpRequest` 头，字段是 `messages`）：
应返回中文结构化结果，且缺失字段标 `[缺失]` 而非当 0 硬算。
