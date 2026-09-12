# 交付前清理清单 · shangzhu2/development

> 调查时间：2026-09-12 ·
> 分支：`shangzhu2/development @ 066000c` ·
> **仅调查，未修改任何文件**

---

## 一、调查结论（先看这个）

| 维度 | 实际状态 | 判断 |
|------|----------|------|
| 分支 / 远程 | `shangzhu2/development` **只在本地**，GitHub 远程只有 `origin/main` | ❌ 并未推送到 GitHub |
| 测试 | **265 通过 / 5 失败** | ❌ 未达可交付 |
| 测试覆盖 | 33 个测试文件中 **8 个游离在 `make test` 之外** | ❌ 门禁有盲区 |
| 语法 / 导入 | `compileall` 通过；`web_server` 可导入，19 条路由 | ✅ |
| 依赖 | `.venv` 有 fastapi 0.135.1 + uvicorn 0.41.0 | ✅ 可启动 |
| 工作区 | 8 个未提交改动（成本归因功能，9-8 20:31~20:48） | ⚠️ 未纳入版本控制 |

**关键判定**：把基线提交 `066000c` 单独检出（临时 worktree）跑测试，结果同为 **5 失败**。
→ **这 5 个失败是既有问题，不是未提交改动引入的回归。** 未提交改动既不修复也不加重它。

---

## 二、P0 · 阻塞交付（必须处理）

### P0-1 ⛔ 5 个测试失败 —— 根因是「阶梯依赖」违背核心设计原则

失败用例（同一根因）：

| # | 测试文件 | 用例 |
|---|----------|------|
| 1 | `tests/test_quick_scan_phase0.py` | `test_rent_plus_revenue_shows_profit_not_false_alarm` |
| 2 | `tests/test_phase1_flexibility.py` | `test_industry_template_with_vc_uncertainty` |
| 3 | `tests/test_phase1_flexibility.py` | `test_rent_plus_revenue_shows_scenarios_and_narrative` |
| 4 | `tests/test_phase4_workbench.py` | `test_p46_t1t2_open_no_rent` |
| 5 | `tests/test_derived.py` | `test_dv3_missing_labor` |

**根因证据**（实跑输出，非推测）：

```
输入 {"monthly_rent":8000, "monthly_revenue":50000, "variable_cost_ratio":0.4}
  人数来源: [阶梯] monthly_revenue=50000 → employee_count=3    ← 测试期望 [缺失]
  固定成本: 8000   利润: 22000

输入 {"monthly_revenue":20000, "employee_count":2, "avg_salary":4000}
  租金来源: [阶梯] employee_count=2 → monthly_rent=3000        ← 测试期望 [缺失]
```

**冲突点**：

1. `config/step_rules.yaml` 把 `monthly_rent`、`employee_count` 配置为可自动推算。
   但 `CALCULATION_PHILOSOPHY.md` 第 52 行明确二者属 **A 类（纯输入）**：
   > 用户给 → 用用户值；不给 → **None（绝不虚构）**

2. 产出的来源标记 `[阶梯]` 是**「来源标注六义」之外的第七种**。
   `CALCULATION_PHILOSOPHY.md` 第 86~95 行定义的六义只有：
   `[用户] [意图] [底线] [推算] [候选] [缺失]` —— 没有 `[阶梯]`，破坏标注封闭性。

3. 后果是产品承诺被破坏：用户只说"月营收 5 万"，系统悄悄编出"租金 3000"。
   这与 README 首页承诺的「说清我们知道什么、猜了什么、缺什么」直接矛盾——
   它既没说"猜"，也没标"缺"，而是当成一个来源明确的数字输出。

**三个修复方向（需你定夺，未执行）**：

- **A. 收口到既有语义**（改动最小、最符合哲学）：
  阶梯推算结果归入 `[候选]`（"待确认"语义已有），并**只在用户未给且无其他来源时**生效；
  同时改 `workflow_engine.py:159` 去掉自创的 `[阶梯]` 标记。
- **B. 加门禁开关**：`step_rules.yaml` 默认关闭，需显式开启才推算；
  或整份规则降级为"建议"（进 `assumptions` 而非直接写进 `params`）。
- **C. 整体回滚 S4**：删除 `step_rules.yaml` + `workflow_engine` 阶梯段 + `test_simulator_upgrade.py` 的 S4 部分。

> 提醒：`test_simulator_upgrade.py`（S4 的正向测试）**也没被 `run_all.py` 收录**，
> 所以"新增功能有测试"是错觉——它既没保护旧行为，自己也没进门禁。

---

### P0-2 ⛔ `web_server_v2.py` 是损坏的死文件

- **未被任何代码/脚本引用**（全仓 grep：0 命中），`start.sh` / `Makefile` 都只用 `web_server.py`。
- **文件本身无法运行**：第 27 行直接 `@app.post("/checkpoint")`，
  但其上方只有 `import os / import sys`，**没有导入 FastAPI、也没有定义 `app`**。
- 它已被 git 跟踪（`066000c` 新增 1358 行），属于"进了版本库但根本跑不起来"的坏文件。

**处理**：删除并提交（或确认这是待续功能，则补齐头部后接入主入口）。

---

### P0-3 ⛔ 8 个测试文件游离在 `make test` 之外

`tests/run_all.py` 只引用 25 个模块，以下 8 个**不会被 `make test` 跑到**：

```
test_advisor_endpoints      test_cost_attribution     ← 新增未提交
test_advisor_formatter      test_industry_seasonal    ← 新增未提交
test_cors_config            test_llm_settings
test_simulator_upgrade      test_vc_consistency
```

> 注意其中 `test_simulator_upgrade` / `test_cost_attribution` / `test_industry_seasonal`
> 正是近期新增功能的正向测试。它们不进门禁，等于**新增功能没有回归保护**。

**处理**：把 8 个模块注册进 `run_all.py` 的 `(mod, label)` 列表，跑通后固化为门禁。

---

### P0-4 ⚠️ 8 个未提交改动（成本归因功能）未纳入版本控制

```
 M config/industry_templates.yaml      (+7)
 M src/router/formatter.py             (+134)
 M src/router/intent.py                (+28)
 M src/tools/workflow_engine.py        (+39)
 M web_server.py                       (+198)
?? src/tools/cost_attribution.py        (新增 5.2KB)
?? tests/test_cost_attribution.py       (新增 9.9KB)
?? tests/test_industry_seasonal.py      (新增 5.1KB)
```

**处理**：确认功能完成度后提交，或明确标注为 WIP 另存分支。

---

### P0-5 ⚠️ 分支未推送 —— 与你"检查 GitHub 里的分支"的前提不符

- 远程 `origin` 仅有 `origin/main`；`shangzhu2/development` **不存在于 GitHub**。
- 另外本机网络访问 GitHub 目前不通（`CONNECT tunnel failed, response 502`，代理问题），
  推送前需先解决代理。

---

## 三、P1 · 需要清理（不影响运行，但影响交付整洁度）

### P1-6 空壳遗留模块（B 路径 / Coze 残留，全部 0 行、0 引用）

| 路径 | 行数 | 引用 |
|------|------|------|
| `src/graphs/__init__.py` | 0 | 无 |
| `src/graphs/nodes/__init__.py` | 0 | 无 |
| `src/agents/__init__.py` | 0 | 无 |
| `src/storage/s3/__init__.py` | 0 | 无 |
| `src/storage/database/__init__.py` | 0 | 无 |
| `src/storage/database/shared/__init__.py` | 0 | 无 |

> `src/storage/local_store.py` **有用**（`web_server.py:126` + 3 个测试引用），不要动。
> `src/graphs/`、`src/agents/`、`src/storage/s3/`、`src/storage/database/` 四个目录可直接删。

### P1-7 死代码 `src/utils/file/file.py`（325 行，0 引用）

- 全仓无任何 import；顶层 import 了 `requests` / `chardet` / `pptx`，
  而后两者**只存在于 `pyproject.toml` 的 `coze-platform` extra（B 路径）**，不在主依赖。
- 即"一份没人用、还牵着 B 路径依赖"的文件，属纯技术债。

### P1-8 `.gitignore` 有重复段落

`# 测试/运行产物` 起的那 7 行（`.pytest_cache/ .coverage web_server.log *.log logs/ reports/`）
**完整出现两次**（约第 50 行与第 62 行），应合并去重。

### P1-9 文档时效性

- README 第 93 行写「全量 **270 用例**」，实际 270（265 通过 + 5 失败），
  **数字对但掩盖了失败**，建议补一句当前通过率或修完再改口径。
- 根目录 4 份 PLAN 文档，跨 8/06 ~ 9/08：

  | 文件 | 最后修改 | 备注 |
  |------|----------|------|
  | `PLAN.md` | 08-06 | 最早，可能已过期 |
  | `PLAN_CALCULATION_FLOW_REFACTOR.md` | 08-20 | 需确认是否已落地 |
  | `PLAN_ADVISOR_PANEL.md` | 08-28 | 需确认是否已落地 |
  | `PLAN_SIMULATOR_UPGRADE.md` | 09-08 | 对应 P0-1 的 S4，**正是冲突来源** |

  建议：已落地的归档到 `docs/archive/`，未落地的标注状态。

---

## 四、P2 · 建议（可选，不阻塞）

1. **端口默认值不一致**：`Makefile` 用 `PORT ?= 8000`，`start.sh` 用 `PORT="${PORT:-8081}"`，
   README 示例又是 `./start.sh -p 8000`。三处三个值，建议统一。
2. **`.venv` 软链到 WPS 灵犀的 Python**（`.../WPS 灵犀/python-env/bin/python3.12`）：
   当前依赖齐全可用，但 WPS 一旦卸载/升级，环境即崩。建议重建为项目内独立 venv。
3. **新克隆环境无法跑 p49 测试**：`test_p49_health_and_footer_single_source` 依赖
   `config/agent_llm_config.json`，而该文件被 `.gitignore` 忽略（本地存在才通过）。
   建议加 `conftest` 兜底生成或改为可跳过语义。
4. `logs/web_server.log`、`output/model_project.xlsx`、`reports/*.md` 均在工作区物理存在，
   虽已被 `.gitignore` 覆盖（未进版本库），交付前可清理以示整洁。

---

## 五、建议执行顺序

```
① 定夺 P0-1 修复方向（A/B/C）→ 修 5 个失败
② 删 web_server_v2.py（P0-2）
③ 8 个测试注册进门禁 + 跑通（P0-3）
④ 提交未提交的 8 个改动（P0-4）
⑤ 清理空壳模块 + 死代码 + .gitignore 去重（P1-6/7/8）
⑥ 文档收口（P1-9）
⑦ 解决代理 → 推送 shangzhu2/development（P0-5）
⑧ P2 按需
```

**验收断言**：`make test` 输出 `0 failed` → 且 `git ls-files | grep -c web_server_v2` 为 0
→ 且 `git ls-remote origin | grep shangzhu2/development` 有输出。
