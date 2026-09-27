# shangzhu · 创业者商业建模工作台

> 把早期创业者那些**稀疏、半知半解**的参数，从「算出一个确定性答案」，变成「说清我们知道什么、猜了什么、缺什么」。

面向中国小微企业主与个体创业者的本地财务建模工作台——开一家牛肉面店、咖啡馆、夫妻店这类真实场景，而不是融资路演用的精美模型。

**English version: [README_EN.md](README_EN.md)**

---

## 它和"财务计算器"有什么不同

多数计算器默认你能填全所有数字；填不出来，它照样给你一个看起来很确定的结果。但早期创业者的真实处境是：**根本不知道**自己的变动成本率、客流爬坡曲线、总投资额。

shangzhu 用三层设计回应这件事：

| 层 | 做什么 |
|---|---|
| **薄规则引擎** | 意图识别、参数抽取、财务计算全是确定性代码。业务意图 **0 次 LLM 调用**——可复现、可测试、不会 hallucinate |
| **置信层** | 每个输出数字都带来源标注：`[用户]` / `[默认]` / `[推算]` / `[缺失]` |
| **缺口策略** | 数据缺失时直接标 `缺失` 并说明缺什么，**绝不把未知当 0** 硬算出一个"确定"的答案 |

LLM 在这里不是计算者，而是 **Engine Steward（只读协作者）**：只在闲聊与「AI 解读」按钮时被召唤，只能读取当前会话的真实参数，不允许自由发挥编造数字。

> **未配置 API Key 也能完整使用**：规则引擎不依赖 LLM，未配置时引擎与界面照常工作，仅 AI 解读自动跳过。

---

## 快速开始

```bash
git clone https://github.com/chuanzhang-lab/shangzhu.git
cd shangzhu
bash setup.sh     # 装依赖 + 生成配置 + 初始化数据库(可选) + 跑测试
./start.sh        # 启动，默认 http://localhost:8081
```

`setup.sh` 会自动：安装 `uv`（如缺失）→ `uv sync` → 生成 `config/agent_llm_config.json` 与 `config/storage.json` → 导入冒烟 → 初始化 PostgreSQL（检测不到则跳过）→ 跑测试。

可选参数：`--start`（跑完直接启动）、`--no-test`（跳过测试）。

### 手动方式

```bash
uv sync                                                        # 1. 装依赖
cp config/agent_llm_config.json.example config/agent_llm_config.json   # 2. 可选：填 model/base_url/api_key
./start.sh                                                     # 3. 启动（默认 8081）
PORT=9000 ./start.sh                                           # 换端口（读 PORT 环境变量）
```

> 依赖由 `uv` + `pyproject.toml` 管理，**没有 `requirements.txt`**；`.venv` 不入库，新克隆必须先 `uv sync` 或 `bash setup.sh`。
> 换端口用 `PORT` 环境变量，`start.sh` 不接受 `-p` 参数。

---

## 30 秒看它怎么工作

**你说一句大白话：**

```
我打算开一家牛肉面店，月租金8000，日均客流80，客单价25，员工2人，人均工资5000，变动成本率35%
```

**引擎抽出结构化参数（纯正则，0 次 LLM）：**

```json
{"industry":"餐饮","monthly_rent":8000,"employee_count":2,"avg_salary":5000,
 "daily_traffic":80,"price_per_unit":25,"variable_cost_ratio":0.35}
```

**返回核心指标 + 每个数字的来源：**

| 指标 | 值 | 来源标注 |
|---|---|---|
| 月营收 | 60000 | `[推算]` 客流 × 单价 × 30 天 |
| 月利润 | 21000 | `[推算]` 营收 − 固定 − 变动 |
| 日均保本客流 | 37 人 | `[推算]` |
| 毛利率 | 65% | `[推算]` 1 − 变动成本率 |
| 回本月数 / 现金流跑道 | `null` | `[缺失]` 总投资未提供，**拒绝硬算** |

最后一行是这个项目的核心主张：**不知道就是不知道**。它不会用 0 顶替缺失的总投资，然后告诉你"第 3 个月回本"。

接着你可以继续追问或改参，会话状态跨轮保持：

```
变动成本率改为60        → 重新测算
如果客流降到50呢        → 单变量敏感性
导出 Excel              → 生成报表
```

---

## 12 个行业模板

`config/industry_templates.yaml` 内置 12 个行业，每个带 **12 个月季节系数** + **行业基准区间**（毛利率、回本周期、客流范围、关键风险提示）：

餐饮 · 零售 · SaaS · 教育 · 电商 · 制造 · 宠物 · 医疗 · 金融 · 内容 · 房地产 · 企业服务

模板只提供**假设的默认值**，并且一律标注为 `[默认]`——它从不冒充你亲口说的数字。

---

## 界面与 API

前端是**分类对话工作台**：5 个分类标签（全部/分析/改参/决策/对比）作过滤器，右侧只读参数面板，左侧任务栏，空项目自动灰化。CSS/JS 在 `src/web_static/`。

主要 HTTP 接口：

| 接口 | 用途 |
|---|---|
| `GET /health` | 健康检查（返回 `status` / `model` / `llm_configured` / `sessions` / `store_backend` 等） |
| `POST /chat` | 对话（`task_id` 指定任务，缺省自动新建） |
| `GET/POST /tasks` | 任务列表 / 新建 |
| `PUT /tasks/{id}/rename` | 任务改名 |
| `GET /tasks/{id}/messages` | 任务历史 |
| `DELETE /tasks/{id}` | 归档任务（软删） |

日志双写：`logs/web_server.log`（应用结构化日志，10 MB × 5 份轮转）与 `logs/shangzhu.log`（控制台副本 + uvicorn 输出）。

---

## 配置

**模型配置**（可选）单源在 `config/agent_llm_config.json` 的 `config.model`，`base_url` / `api_key` 同在此文件，三者同源以避免跨厂商错配。该文件被 gitignore，模板见 `config/agent_llm_config.json.example`。

API Key 四级优先级读取：

1. `config/agent_llm_config.json`（与 model/base_url 同源）
2. 环境变量 `DEEPSEEK_API_KEY` / `LONGCAT_API_KEY` / `LLM_API_KEY`
3. macOS Keychain（service=`shangzhu-llm`, account=`api_key`）
4. 空串（未配置）

**持久化**默认 `postgresql://<系统用户名>@localhost:5432/shangzhu`，可用 `PGDATABASE_URL` 或 `config/storage.json` 的 `db_url` 覆盖。降级链：**PostgreSQL → 本地 JSON 文件 → 内存**，前两级重启不丢。PG 不可用时服务不崩，仅会话在重启后丢失。

两个含密钥/本机信息的配置文件均为 `600` 权限且不被 git 跟踪。数据库备份：`./scripts/backup_db.sh shangzhu`（保留最近 7 份）。

---

## 开发

```bash
make sync      # uv sync
make test      # 全量回归（当前 449 passed）
make smoke     # 导入 + /health 结构冒烟（不启服务）
make compile   # 字节码编译检查
make start     # 启动（PORT=8081）
make health    # curl /health
```

测试覆盖引擎全链路：`router`（意图/参数抽取）→ `session_state`（跨轮 merge）→ `workflow_engine` → `financial_calculator` → `formatter` → `llm_advisor`，以及多轮真实场景对话的端到端 oracle。

工程约束：单条消息超过 10,000 字符直接返回 400；会话带 4 小时 TTL 与 1000 条上限；工具返回异常时给结构化错误而非 500。

深入设计见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)、[`docs/CALCULATION_PHILOSOPHY.md`](docs/CALCULATION_PHILOSOPHY.md)、[`docs/ENGINEERING_DESIGN.md`](docs/ENGINEERING_DESIGN.md)。

---

## 免责声明

本工具输出的测算基于**你提供的参数**与**行业经验假设**，用于辅助思考与敏感性分析，**不构成投资或经营决策建议**。真实创业决策请结合自身尽调与专业财务意见。

---

## 许可证

[MIT](LICENSE) © 2026 chuanzhang-lab
