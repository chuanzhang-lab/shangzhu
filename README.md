# 创业者商业建模工作台

**版本：v0.1.0** — 本版本将大模型设为交互助手并添加了功能 `aab3a12`

把早期创业者的稀疏 / 未知参数，从「算出一个确定性答案」转变为「说清我们知道什么、猜了什么、缺什么」。薄规则引擎（0 次 LLM 调用业务意图）+ 置信层（来源标注 `[用户]/[默认]/[推算]/[缺失]`）+ 只读 LLM 协作层（Engine Steward）。

## 交付边界（重要）

本仓**只交付 (A) 本地独立工作台**。Coze 平台服务 (B) 由平台侧保障，**非本仓交付物**，本地不装其重型依赖、也不测。

- **(A) 本地独立工作台（本仓交付）**：`web_server.py` 规则引擎 + Engine Steward。业务意图 0 次 LLM 调用；chitchat/闲聊走**已接入的 Engine Steward（只读、接地真实项目背景）**，不引入自由 agent，从设计上杜绝编造未出现的具体数字。含任务栏与会话持久化（本机 PostgreSQL）。前端为**方案二「分类对话工作台」**：5 个分类标签（全部/分析/改参/决策/对比）作过滤器、按分类分草稿、空项目自动灰化、右侧只读参数面板，CSS/JS 位于 `src/web_static/`。
- **(B) Coze 平台服务（已从本仓移除）**：原 `src/main.py` LangGraph agent 循环及 `storage/*`（sqlalchemy/boto3/cozeloop 等）为 Coze 平台专用路径，2026-08-01 清理——本地 web_server 与其零耦合，也不再交付这些重型依赖。

## 一键启动（推荐）

**无需关心当前目录。从仓库根目录或 `~` 直接跑都行**——`setup.sh` 会自动切到脚本所在目录。

### 方案一：完整 Clone（推荐，留项目文件）

```bash
git clone https://github.com/chuanzhang-lab/claude.git && cd claude && bash setup.sh
```

效果：完整克隆到本地，可继续开发使用。

### 方案二：gh CLI 克隆（私有仓库推荐）

```bash
gh repo clone chuanzhang-lab/claude && cd claude && bash setup.sh
```

`gh` 已登录时会自动处理认证，比裸 `git clone` 省事（本仓是私有仓库，见下方注意事项）。

### `setup.sh` 自动完成

1. 切到脚本所在目录（解决"找不到文件"问题）
2. 安装依赖（`uv sync`；检测不到 `uv` 时自动安装）
3. 生成 `config/agent_llm_config.json` 与 `config/storage.json`（两者被 gitignore，新克隆必然缺失）
4. 导入冒烟（提前暴露依赖问题，不半途启动）
5. 初始化 PostgreSQL（**可选**：检测不到 PG 时跳过，服务自动降级内存存储，不崩）
6. 跑测试（**270 passed**）

### 可选参数

```bash
bash setup.sh            # 完整初始化 + 跑测试（首次推荐）
bash setup.sh --start    # 上述全部 + 结束后直接启动服务
bash setup.sh --no-test  # 只做环境准备，跳过测试
```

### 适用场景

| 场景 | 推荐做法 |
|------|----------|
| 第一次使用 | 方案一（留项目文件） |
| 只想验证环境是否 OK | `bash setup.sh --no-test` |
| 装完直接跑起来 | `bash setup.sh --start` |

> ⚠️ **注意事项**
> - 本仓库为**私有仓库**，未认证时 `git clone` 会失败。请先 `gh auth login`，或直接用方案二。
> - 私有仓库**不支持** `curl raw.githubusercontent.com … | bash` 一行式安装（会返回 404），请用上面的克隆方式。
> - 依赖由 `uv` + `pyproject.toml` 管理，**没有 `requirements.txt`**。
> - 首次使用请先克隆、本地审阅后再执行，不要直接 `curl | bash`（供应链风险）。

## 手动启动（已克隆 / 已有项目目录）

```bash
# 1. 安装依赖（首次）
uv sync

# 2. 配置模型（可选；未配置时规则引擎照常工作，AI 解读自动跳过）
#    编辑 config/agent_llm_config.json 填入 model / base_url / api_key
#    或启动后直接在网页右上角的设置入口里填写

# 3. 初始化数据库（可选，会话/任务持久化用）
.venv/bin/python3 scripts/init_db.py

# 4. 启动服务（默认端口 8081）
./start.sh
# 换端口：PORT=8000 ./start.sh   （注意：不是 -p 参数）
```

> 会话/任务持久化依赖本机 PostgreSQL（默认 `localhost:5432/shangzhu`，可用 `PGDATABASE_URL` 覆盖）。PG 不可用时自动降级为进程内内存存储，服务不崩，但重启后会话丢失。

启动后：
- `GET  /health` 健康检查（返回 `status` / `model` / `version` / `uptime_seconds` / `llm_configured` / `sessions` / `store_backend`）
- `POST /chat` 对话（请求体见 `web_server.py` 的 `ChatRequest`；`task_id` 指定任务，缺省自动新建）
- `GET/POST /tasks` 任务列表 / 新建任务（左侧任务栏）
- `PUT /tasks/{id}/rename` 任务改名
- `GET /tasks/{id}/messages` 任务历史
- `DELETE /tasks/{id}` 归档任务（软删，历史保留）
- 日志输出到 `logs/web_server.log`（同时保留控制台输出）

> 注：`start.sh` 只启动 (A)。Coze 平台服务 (B) 依赖已从本仓移除，如需平台端服务应在 Coze 平台环境另行部署。


## 工程命令（可选）

```bash
make test      # 全量引擎层回归
make smoke     # 导入 + 路由冒烟
make compile   # 字节码编译检查
make start     # 等价 ./start.sh -p 8000
```

## 工程化边界
- **输入长度限制**：单条用户消息超过 10,000 字符直接返回 400，避免极端输入拖垮引擎/LLM。
- **会话状态保护**：`compare` / `report_pdf` / `report_excel` / `market` / `benchmark` 等一次性或假设分析意图，本句参数不污染 SessionState base。
- **会话内存管理**：进程内 SessionState 带 4 小时 TTL 与 1000 条上限，自动淘汰过期/最旧会话，防止长期运行内存无限增长。
- **错误处理**：工具返回非 JSON 或解析失败时返回结构化错误，不 500；顶层异常记录完整 traceback 并返回友好提示。
- **统一参数降级（M1）**：`quick_scan` / `trend` / `compare` 对「算不出月利润」（缺变动成本率/成本）等软缺口统一走 `_profit_readiness` 降级提示，绝不硬算假趋势 / 不参与 diff 减法 / 不裸崩。
- **None 消费一致性（M2）**：派生字段（`monthly_profit` / `variable_cost_ratio` / `runway` / `available_cash`）缺失时按「缺失不参与计算 / 按 0 跳过」处理，杜绝「缺失当 0」误报与 None 算术崩溃。
- **前端静态边界（M3）**：前端 CSS/JS 从 `web_server.py` 内联抽取为独立文件 `src/web_static/app.css` / `app.js`，由 FastAPI StaticFiles 挂载到 `/static`；`web_server.py` 仅保留 HTML 骨架与路由。
- **视图层兜底（M4）**：前端数值渲染对 `null` / `undefined` / `NaN` / `Infinity` / 空串统一显示 `—`，杜绝 `undefined` / `NaN%` 泄漏。
- **改参采纳一致性（F1）**：变动成本率采用归一化 `variable_cost_ratio` 为引擎单一消费键；抽取层对「变动成本/可变成本/成本率」统一产出，merge 层双键同步（`variable_cost_rate` → `ratio/100`），主对话与 compare 两条改参路径行为一致。
- **前端状态单一真相源（F2）**：`tasksCache[当前任务].params` 为权威缓存——`send()` 收到新参数即写回、`switchTask`/`restoreTaskParams` 从它恢复（必要时防陈旧刷新）、`loadTasks` 刷新同步；修复「切任务后改参/决策上下文丢失」。
- **改参即时反馈（F3）**：改参动作后校验后端是否真采纳，toast「✅已更新 / ⚠️未采纳」，变更字段短暂高亮；`pcRecalc` 只发改动字段、改参输入框支持回车单字段提交；compare 控件对变动成本率有百分比提示并预填当前值。
- **交互状态可观测（F5）**：导出前校验参数完整性（缺营收/变动成本/固定成本则提示并拦截）；新建任务失败给红字反馈；任务改名带成功/失败 toast。

## 配置
- 模型：**单源**为 `config/agent_llm_config.json` 的 `config.model`（`base_url` / `api_key` 同在此文件，三者同源以避免跨厂商错配）。改这一处即全局生效——`/health`、首页页脚、启动日志、Engine Steward 均从此读取，无第二处硬编码。该文件被 gitignore，**README 不写死具体模型名**（否则换模型必漂移），本地实际值以上述配置文件为准；代码层 fallback 默认值见 `config/settings.py` 与 `src/llm_advisor.py`。
- 数据库：默认 `postgresql://newmacbook@localhost:5432/shangzhu`。可通过以下方式覆盖：
  - 环境变量 `PGDATABASE_URL`（最高优先级）
  - `config/storage.json` 中的 `db_url` 字段（中等优先级，文件被 gitignore）
  - `config/storage.json.example` 为模板文件，复制为 `storage.json` 后修改即可
- 存储降级链：PG → 本地 JSON 文件 → 内存。前两级重启不丢，最后一级仅作兜底。

## 安全
- **API Key 管理**：四级优先级读取（配置单源优先，与 model/base_url 同源，避免跨厂商错配）：
  1. `config/agent_llm_config.json`（设置页保存的 key，与 model/base_url 同源）
  2. 环境变量 `DEEPSEEK_API_KEY` / `LONGCAT_API_KEY` / `LLM_API_KEY`
  3. macOS Keychain（service=`shangzhu-llm`, account=`api_key`）
  4. 空串（未配置）
- env / Keychain 仅在 config 未写 key 时兜底；若需用环境变量覆盖 config，请先清空设置页的 key。
- **CORS**：白名单限制为 `http://127.0.0.1:8080` 和 `http://localhost:8080`，POST 类操作要求 `X-Requested-With` 头防 CSRF。
- **配置文件权限**：`config/storage.json` 和 `config/agent_llm_config.json` 均为 `600`，不会被 git 跟踪。
- **备份**：定期执行 `./scripts/backup_db.sh shangzhu` 备份数据库，备份文件在 `backups/` 目录，自动保留最近 7 份。

## 测试（仅覆盖 A：本地引擎层）

```bash
.venv/bin/python3 tests/run_all.py
```
- 测试只覆盖**本地引擎层 (A)**：`router`(参数抽取/意图) → `session_state`(跨轮 merge) → `workflow_engine`(quick_scan) → `financial_calculator` → `formatter` → `llm_advisor`(Engine Steward) 全链路，以及 12 轮羊肉汤店对话集成 oracle。另含本地存储层（`test_local_store`）与任务 CRUD API（`test_task_api`）。当前全量 **270 用例**（含 2026-08-19 新增的 trend 统一降级与 None 防御回归、2026-08-21 资源泄漏修复回归、2026-08-28 顾问面板与前端交互修复回归、2026-09-05 并发/安全/资源生命周期修复回归）。
- **不覆盖 (B) Coze 路径**：该路径已从本仓移除；解耦由 `tests/test_phase4_workbench.py` 的 `test_p48_*` 硬性守护（断言 `web_server.py` 不得 import `agents.agent` / `build_agent` / `get_agent`）。

## 依赖分组（clone 后注意）

`pyproject.toml` 已按交付边界做依赖分组：

- **主依赖（本地工作台 A 必需）**：FastAPI / uvicorn / pydantic / langchain / langchain-openai / langgraph / langsmith / rich 等轻量依赖，以及引擎自身的纯 Python 模块。
- **`coze-platform` extra（Coze 平台服务 B 专属）**：boto3 / sqlalchemy / opencv / pptx / cozeloop 等重型平台库，本地不交付、不装也能跑 (A)。

本地运行 (A) 只需：

```bash
uv sync                # 默认只装主依赖（A 必需），不碰重型平台库
./start.sh             # 启动本地服务
```

部署到 Coze 平台时再装全量：

```bash
uv sync --extra coze-platform
```

> 注：本仓已附完整 `.venv`（含全部依赖），直接 `./start.sh` 即可运行，无需重新 sync。

## 本地 Agent 冒烟测试
```bash
.venv/bin/python local_test.py        # 打印真实模型配置并跑一条示例对话（需 DEEPSEEK_API_KEY）
```
