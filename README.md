# shangzhu · 创业者商业建模工作台 / Business Modeling Workbench for First-Time Founders

> 把早期创业者那些**稀疏、半知半解**的参数，从「算出一个确定性答案」，变成「说清我们知道什么、猜了什么、缺什么」。
>
> Early-stage founders don't have complete numbers. shangzhu turns your sparse, half-guessed assumptions into a model that says clearly: **what we know, what we assumed, and what's missing** — instead of pretending to compute one "certain" answer.

面向中国小微企业主与个体创业者的本地财务建模工作台——开一家牛肉面店、咖啡馆、夫妻店这类真实场景，而不是融资路演用的精美模型。

A local-first financial modeling workbench for micro-entrepreneurs opening a noodle shop, coffee stand, or family-run store — real main-street businesses, not polished pitch-deck models.

**English edition (separate repo): [chuanzhang-lab/shangzhu-en](https://github.com/chuanzhang-lab/shangzhu-en)**

---

## 它和"财务计算器"有什么不同 / How It Differs from a "Financial Calculator"

多数计算器默认你能填全所有数字；填不出来，它照样给你一个看起来很确定的结果。但早期创业者的真实处境是：**根本不知道**自己的变动成本率、客流爬坡曲线、总投资额。

Most calculators assume you can fill in every field; if you can't, they still hand you a confident-looking result. But the real situation of an early founder is: **you don't know** your variable cost ratio, your ramp-up curve, or your total investment.

shangzhu 用三层设计回应这件事：

shangzhu answers this with a three-layer design:

| 层 / Layer | 做什么 / What It Does |
|---|---|
| **薄规则引擎 / Thin Rule Engine** | 意图识别、参数抽取、财务计算全是确定性代码。业务意图 **0 次 LLM 调用**——可复现、可测试、不会 hallucinate / Intent recognition, parameter extraction, and financial calculation are all deterministic code. Business logic with **zero LLM calls** — reproducible, testable, no hallucination |
| **置信层 / Confidence Layer** | 每个输出数字都带来源标注：`[用户]` / `[默认]` / `[推算]` / `[缺失]` / Every output number carries a source tag: `[user]` / `[default]` / `[derived]` / `[missing]` |
| **缺口策略 / Gap Strategy** | 数据缺失时直接标 `缺失` 并说明缺什么，**绝不把未知当 0** 硬算出一个"确定"的答案 / When data is missing, mark it `missing` and explain what's needed. **Never treat unknown as 0** and force a "certain" answer |

LLM 在这里不是计算者，而是 **Engine Steward（只读协作者）**：只在闲聊与「AI 解读」按钮时被召唤，只能读取当前会话的真实参数，不允许自由发挥编造数字。

LLM here is not the calculator — it is the **Engine Steward (read-only collaborator)**: only invoked during free chat and the "AI Interpretation" button, can only read the session's real parameters, and is forbidden from inventing numbers.

> **未配置 API Key 也能完整使用**：规则引擎不依赖 LLM，未配置时引擎与界面照常工作，仅 AI 解读自动跳过。
>
> **Works fully without an API key**: the rule engine does not depend on an LLM. When unconfigured, the engine and UI function normally — only AI interpretation is skipped.

---

## 快速开始 / Quick Start

```bash
git clone https://github.com/chuanzhang-lab/shangzhu.git
cd shangzhu
bash setup.sh     # 装依赖 + 生成配置 + 初始化数据库(可选) + 跑测试
./start.sh        # 启动，默认 http://localhost:8081
```

`setup.sh` 会自动：安装 `uv`（如缺失）→ `uv sync` → 生成 `config/agent_llm_config.json` 与 `config/storage.json` → 导入冒烟 → 初始化 PostgreSQL（检测不到则跳过）→ 跑测试。

`setup.sh` automates: install `uv` (if missing) → `uv sync` → generate `config/agent_llm_config.json` and `config/storage.json` → smoke import → initialize PostgreSQL (skipped if not detected) → run tests.

可选参数：`--start`（跑完直接启动）、`--no-test`（跳过测试）。

Optional flags: `--start` (launch after setup), `--no-test` (skip tests).

### 手动方式 / Manual Setup

```bash
uv sync                                                        # 1. 装依赖 / install deps
cp config/agent_llm_config.json.example config/agent_llm_config.json   # 2. 可选：填 model/base_url/api_key
./start.sh                                                     # 3. 启动（默认 8081）
PORT=9000 ./start.sh                                           # 换端口（读 PORT 环境变量）
```

> 依赖由 `uv` + `pyproject.toml` 管理，**没有 `requirements.txt`**；`.venv` 不入库，新克隆必须先 `uv sync` 或 `bash setup.sh`。
>
> Dependencies are managed by `uv` + `pyproject.toml`; **there is no `requirements.txt`**. `.venv` is git-ignored — after cloning you must run `uv sync` or `bash setup.sh` first.
>
> 换端口用 `PORT` 环境变量，`start.sh` 不接受 `-p` 参数。
>
> Change the port with the `PORT` environment variable; `start.sh` does not accept a `-p` flag.

---

## 30 秒看它怎么工作 / See It Work in 30 Seconds

**你说一句大白话 / You say one plain sentence:**

```
我打算开一家牛肉面店，月租金8000，日均客流80，客单价25，员工2人，人均工资5000，变动成本率35%

I plan to open a noodle shop. Monthly rent 8000, avg daily traffic 80, avg ticket 25,
2 employees at 5000/mo each, variable cost ratio 35%
```

**引擎抽出结构化参数（纯正则，0 次 LLM）/ Engine extracts structured parameters (pure regex, zero LLM calls):**

```json
{"industry":"餐饮 / restaurant","monthly_rent":8000,"employee_count":2,"avg_salary":5000,
 "daily_traffic":80,"price_per_unit":25,"variable_cost_ratio":0.35}
```

**返回核心指标 + 每个数字的来源 / Returns core metrics plus a source tag for every number:**

| 指标 / Metric | 值 / Value | 来源标注 / Source |
|---|---|---|
| 月营收 / Monthly Revenue | 60000 | `[推算]` 客流×单价×30天 / `[derived]` traffic × price × 30 |
| 月利润 / Monthly Profit | 21000 | `[推算]` 营收−固定−变动 / `[derived]` rev − fixed − variable |
| 日均保本客流 / Daily Breakeven Traffic | 37 | `[推算]` / `[derived]` |
| 毛利率 / Gross Margin | 65% | `[推算]` 1−变动成本率 / `[derived]` 1 − variable cost ratio |
| 回本月数 / Payback Months | `null` | `[缺失]` 总投资未提供，**拒绝硬算** / `[missing]` total investment not given; **refuses to force-calculate** |

最后一行是这个项目的核心主张：**不知道就是不知道**。它不会用 0 顶替缺失的总投资，然后告诉你"第 3 个月回本"。

The last row is this project's core claim: **unknown means unknown**. It won't substitute 0 for the missing total investment and then tell you "payback in month 3."

接着你可以继续追问或改参，会话状态跨轮保持 / You can then keep asking or change parameters — session state persists across turns:

```
变动成本率改为60        → 重新测算 / re-solve
如果客流降到50呢        → 单变量敏感性 / single-variable sensitivity
导出 Excel              → 生成报表 / generate report
```

---

## 12 个行业模板 / 12 Industry Templates

`config/industry_templates.yaml` 内置 12 个行业，每个带 **12 个月季节系数** + **行业基准区间**（毛利率、回本周期、客流范围、关键风险提示）：

`config/industry_templates.yaml` ships with 12 industries, each with **12-month seasonality factors** + **industry benchmark ranges** (gross margin, payback period, traffic range, key risk signals):

餐饮 · 零售 · SaaS · 教育 · 电商 · 制造 · 宠物 · 医疗 · 金融 · 内容 · 房地产 · 企业服务
Restaurant · Retail · SaaS · Education · E-commerce · Manufacturing · Pet · Healthcare · Finance · Content · Real Estate · Enterprise Services

模板只提供**假设的默认值**，并且一律标注为 `[默认]`——它从不冒充你亲口说的数字。

Templates only provide **default assumptions**, always tagged as `[default]` — they never pretend to be numbers you said yourself.

---

## 界面与 API / UI & API

前端是**分类对话工作台**：5 个分类标签（全部/分析/改参/决策/对比）作过滤器，右侧只读参数面板，左侧任务栏，空项目自动灰化。CSS/JS 在 `src/web_static/`。

The frontend is a **categorized conversation workbench**: 5 category tabs (All / Analysis / Edit Params / Decision / Comparison) as filters, a read-only parameter panel on the right, a task list on the left, empty projects auto-grayed. CSS/JS live in `src/web_static/`.

主要 HTTP 接口 / Main HTTP Endpoints:

| 接口 / Endpoint | 用途 / Purpose |
|---|---|
| `GET /health` | 健康检查（返回 `status` / `model` / `llm_configured` / `sessions` / `store_backend` 等） / Health check (returns `status` / `model` / `llm_configured` / `sessions` / `store_backend` etc.) |
| `POST /chat` | 对话（`task_id` 指定任务，缺省自动新建） / Chat (`task_id` selects a task; creates a new one if omitted) |
| `GET/POST /tasks` | 任务列表 / 新建 / Task list / Create |
| `PUT /tasks/{id}/rename` | 任务改名 / Rename task |
| `GET /tasks/{id}/messages` | 任务历史 / Task history |
| `DELETE /tasks/{id}` | 归档任务（软删） / Archive task (soft delete) |

日志双写：`logs/web_server.log`（应用结构化日志，10 MB × 5 份轮转）与 `logs/shangzhu.log`（控制台副本 + uvicorn 输出）。

Dual log output: `logs/web_server.log` (structured application log, 10 MB × 5 rotations) and `logs/shangzhu.log` (console copy + uvicorn output).

**排障口诀 / Troubleshooting checklist**（问题先分清「服务端还是前端」/ First decide: server-side or front-end）：

1. 先看 `logs/web_server.log`——服务端异常、降级、前端上报（`WEBCLIENT` 标签）都在这里；
2. 再看浏览器 console 的 `[失败于[阶段:错误码]]` 标记——前端失败会注明阶段（loadTasks / switchTask / chat 等），一眼定位到功能块；
3. 页面行为怪但两处都干净 → 大概率旧前端缓存：硬刷新（Cmd+Shift+R），或看顶部「页面版本过旧」横幅；
4. 测试跑完任务列表混入测试数据 → `scripts/clean_test_tasks.py`（默认 dry-run）清理；新版本测试已隔离，正常不再产生。

Check `logs/web_server.log` first (server errors, degradations, `WEBCLIENT` front-end reports), then the browser console `[失败于[stage:code]]` markers to locate the failing feature block. Clean log + weird UI usually means stale front-end cache: hard-refresh (Cmd+Shift+R) or heed the "page version outdated" banner.

---

## 配置 / Configuration

**模型配置 / Model Configuration**（可选 / optional）单源在 `config/agent_llm_config.json` 的 `config.model`，`base_url` / `api_key` 同在此文件，三者同源以避免跨厂商错配。该文件被 gitignore，模板见 `config/agent_llm_config.json.example`。

The **model configuration** (optional) is single-sourced in `config/agent_llm_config.json` at `config.model`, with `base_url` and `api_key` in the same file — all three from one source to avoid cross-provider mismatches. The file is gitignored; see `config/agent_llm_config.json.example` for the template.

API Key 四级优先级读取 / API key resolution order (highest priority first):

1. `config/agent_llm_config.json`（与 model/base_url 同源 / same source as model/base_url）
2. 环境变量 `DEEPSEEK_API_KEY` / `LONGCAT_API_KEY` / `LLM_API_KEY`
3. macOS Keychain（service=`shangzhu-llm`, account=`api_key`）
4. 空串（未配置） / empty string (unconfigured)

**持久化 / Persistence** 默认 `postgresql://<系统用户名>@localhost:5432/shangzhu`，可用 `PGDATABASE_URL` 或 `config/storage.json` 的 `db_url` 覆盖。降级链：**PostgreSQL → 本地 JSON 文件 → 内存**，前两级重启不丢。PG 不可用时服务不崩，仅会话在重启后丢失。

Default persistence: `postgresql://<system-username>@localhost:5432/shangzhu`; overridable via `PGDATABASE_URL` or the `db_url` field in `config/storage.json`. Fallback chain: **PostgreSQL → local JSON file → in-memory**; the first two survive restarts. When PG is unavailable the service does not crash — sessions are simply lost on restart.

两个含密钥/本机信息的配置文件均为 `600` 权限且不被 git 跟踪。数据库备份：`./scripts/backup_db.sh shangzhu`（保留最近 7 份）。

The two config files that hold credentials/local information have `600` permissions and are not tracked by git. Database backup: `./scripts/backup_db.sh shangzhu` (keeps the last 7 snapshots).

---

## 开发 / Development

```bash
make sync      # uv sync
make test      # 全量回归（当前 517 passed） / full regression (currently 517 passed)
make smoke     # 导入 + /health 结构冒烟（不启服务） / import + /health smoke (no server)
make compile   # 字节码编译检查 / bytecode compile check
make start     # 启动（PORT=8081） / start (PORT=8081)
make health    # curl /health
```

测试覆盖引擎全链路：`router`（意图/参数抽取）→ `session_state`（跨轮 merge）→ `workflow_engine` → `financial_calculator` → `formatter` → `llm_advisor`，以及多轮真实场景对话的端到端 oracle。

Tests cover the full engine pipeline: `router` (intent/param extraction) → `session_state` (cross-turn merge) → `workflow_engine` → `financial_calculator` → `formatter` → `llm_advisor`, plus end-to-end oracles from real multi-turn dialogue scenarios.

工程约束：单条消息超过 10,000 字符直接返回 400；会话带 4 小时 TTL 与 1000 条上限；工具返回异常时给结构化错误而非 500。

Engineering constraints: messages over 10,000 characters return 400; sessions have a 4-hour TTL and a 1,000-message cap; tool errors return structured errors instead of 500.

深入设计见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)、[`docs/CALCULATION_PHILOSOPHY.md`](docs/CALCULATION_PHILOSOPHY.md)、[`docs/ENGINEERING_DESIGN.md`](docs/ENGINEERING_DESIGN.md)。

Deeper design docs: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/CALCULATION_PHILOSOPHY.md`](docs/CALCULATION_PHILOSOPHY.md), [`docs/ENGINEERING_DESIGN.md`](docs/ENGINEERING_DESIGN.md).

---

## 免责声明 / Disclaimer

本工具输出的测算基于**你提供的参数**与**行业经验假设**，用于辅助思考与敏感性分析，**不构成投资或经营决策建议**。真实创业决策请结合自身尽调与专业财务意见。

All projections are based on **the parameters you provide** and **industry-experience assumptions**, for assisted thinking and sensitivity analysis only — **not investment or business advice**. Make real decisions with your own due diligence and professional financial advice.

---

## 许可证 / License

[MIT](LICENSE) © 2026 chuanzhang-lab
