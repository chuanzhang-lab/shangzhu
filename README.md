# 创业者商业建模工作台

把早期创业者的稀疏 / 未知参数，从「算出一个确定性答案」转变为「说清我们知道什么、猜了什么、缺什么」。薄规则引擎（0 次 LLM 调用业务意图）+ 置信层（来源标注 `[用户]/[默认]/[推算]/[缺失]`）+ 只读 LLM 协作层（Engine Steward）。

## 交付边界（重要）

本仓**只交付 (A) 本地独立工作台**。Coze 平台服务 (B) 由平台侧保障，**非本仓交付物**，本地不装其重型依赖、也不测。

- **(A) 本地独立工作台（本仓交付）**：`web_server.py` 规则引擎 + Engine Steward。业务意图 0 次 LLM 调用；chitchat/闲聊走**已接入的 Engine Steward（只读、接地真实项目背景）**，不引入自由 agent，从设计上杜绝编造未出现的具体数字。含任务栏与会话持久化（本机 PostgreSQL）。前端为**方案二「分类对话工作台」**：5 个分类标签（全部/分析/改参/决策/对比）作过滤器、按分类分草稿、空项目自动灰化、右侧只读参数面板，CSS/JS 位于 `src/web_static/`。
- **(B) Coze 平台服务（已从本仓移除）**：原 `src/main.py` LangGraph agent 循环及 `storage/*`（sqlalchemy/boto3/cozeloop 等）为 Coze 平台专用路径，2026-08-01 清理——本地 web_server 与其零耦合，也不再交付这些重型依赖。

## 快速启动

```bash
# 1. 安装 uv（如未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 创建虚拟环境并安装依赖（首次运行）
uv sync

# 3. 设置 API key（可选；未设置时 Engine Steward 静默跳过，规则引擎照常工作）
export DEEPSEEK_API_KEY="your-key"

# 4. 初始化本地数据库（会话/任务持久化，首次运行或表缺失时）
.venv/bin/python3 scripts/init_db.py

# 5. 启动本地服务
./start.sh -p 8000
```

> `start.sh` 会自动检测 `.venv`；若不存在且已安装 `uv`，会先执行 `uv sync`。
> 会话/任务持久化依赖本机 PostgreSQL（默认 `localhost:5432/shangzhu`，可用环境变量 `PGDATABASE_URL` 覆盖）。PG 不可用时自动降级为进程内内存存储，服务不崩。

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
- 模型：`deepseek-v4-flash`（**单源**：`config/agent_llm_config.json` 的 `config.model`）。改这一处即全局生效——`/health`、首页页脚、启动日志、Engine Steward 均从此读取，无第二处硬编码。
- 密钥：设置环境变量 `DEEPSEEK_API_KEY`（无 `.env` 文件，由运行环境注入）。缺失时 LLM 解读层（Engine Steward）静默跳过，规则引擎照常工作。

## 测试（仅覆盖 A：本地引擎层）

```bash
.venv/bin/python3 tests/run_all.py
```
- 测试只覆盖**本地引擎层 (A)**：`router`(参数抽取/意图) → `session_state`(跨轮 merge) → `workflow_engine`(quick_scan) → `financial_calculator` → `formatter` → `llm_advisor`(Engine Steward) 全链路，以及 12 轮羊肉汤店对话集成 oracle。另含本地存储层（`test_local_store`）与任务 CRUD API（`test_task_api`）。当前全量 **285 用例**（含 2026-08-19 新增的 trend 统一降级与 None 防御回归、2026-08-21 资源泄漏修复回归、2026-08-28 顾问面板与前端交互修复回归）。
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
