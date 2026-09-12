# 交付前完整性与成熟度审计 — 2026-09-12

> 范围：本地独立工作台 (A)。分支 `main @ e4a5dd5`。
> 方法：全仓静态核查 + 真起服务端到端实测 + 逐文件对照。**所有结论均有实证，未采纳任何推测性判断。**

---

## 一、结论先行

| 维度 | 结论 |
|------|------|
| 交付门禁 | ✅ **已从「假绿灯」变为真门禁** —— `make test` = pytest 全量，实测 **355 passed / 0 failed** |
| 可交付性 | ✅ 本地工作台 (A) **已达可交付**：真起服务、`/health` 正常、业务对话链路全通 |
| 内容完整性 | ✅ 无缺失文件、无断链引用、无死代码残留 |
| 残留缺陷 | ⚠️ 3 项（1 项抽取器精度，2 项工程卫生），**均不阻断交付**，见第四节 |
| 待决策 | 4 项，见第五节 |

**判定**：本轮把「内容完整」推进到了「**声明与实现一致**」。剩余问题集中在「产品能力覆盖度」（抽取器措辞）与「工程卫生」（文档归档、venv 可移植性），不属阻断项。

---

## 二、本轮已落地（全部经实证）

### 2.1 门禁真实化（最重要的一项）

**问题**：`tests/run_all.py` 用 `vars(mod)` 只扫**模块级**函数；`class TestXxx` 内的用例**即使被 import 也永远收集不到**。结果 `make test` 只跑 25/33 个文件、报 270 passed，而 pytest 全量是 347 passed / **7 failed**——7 个真实失败（4 个 S4 连带损伤 + 3 个全局状态污染）一个都看不见。

| 修复 | 文件 |
|------|------|
| 门禁改用 pytest 全量收集 | `Makefile`（`test:` 目标）、`README` |
| `setup.sh` 步骤 6 同步改用 pytest，无 pytest 时才退回后备并显式告警 | `setup.sh` |
| 补齐类方法收集 + 注册此前游离门禁外的 8 个测试文件 | `tests/run_all.py` |
| 需要 pytest fixture 的 24 个用例**显式记为 SKIP**（不并入通过、也不误报失败） | `tests/run_all.py` |
| 修 S4 带来的 4 个季节系数断言（改为动态读行业模板，不再写死数值） | `tests/test_simulator_upgrade.py` |
| 修 `CONFIG_PATH` 全局污染（`try/finally` 恢复，`TemporaryDirectory` 退出后不再留悬空路径） | `tests/test_concurrency_fixes.py` |

**实测口径对齐（关键）**：

```
pytest tests/          → 355 passed, 0 failed        ← 交付门禁
tests/run_all.py       → 331 passed, 0 failed, 24 skipped
                          331 + 24 = 355              ← 两者完全对齐，无覆盖差
```

### 2.2 文档漂移修正（README 与实际不符）

| # | 原声明 | 实际 | 处理 |
|---|--------|------|------|
| 1 | `make start` 等价 `./start.sh -p 8000` | `start.sh` **不解析 `-p`**，且默认端口是 8081 | 改为 `PORT=8081 ./start.sh` |
| 2 | 「本仓已附完整 `.venv`…无需重新 sync」 | `.venv` 被 gitignore，**新克隆必然没有** | 改为「必须跑 `setup.sh` / `uv sync`」 |
| 3 | 本地 Agent 冒烟测试 = `.venv/bin/python local_test.py` | 该文件已删，且原内容 `from agents.agent import build_agent`（模块不存在）→ **必然 ImportError** | 删除该段，改为 `make smoke` + `curl /health` |
| 4 | 「全量 270 用例」 | 实际 355 | 更新为 355 passed / 0 failed |
| 5 | 测试命令 `tests/run_all.py` | 非交付门禁 | 改为 `make test` |
| 6 | 日志路径只提 `logs/web_server.log` | 实为**双写**（应用日志 + start.sh 重定向） | 改为双条并列说明 |
| 7 | 数据库默认串写死机器名 `newmacbook` | 不应绑定某台机器 | 改为 `<系统用户名>` |
| 8 | 版本行「本版本将大模型设为交互助手并添加了功能 `aab3a12`」 | 语义含糊、把 commit SHA 当功能名 | 改为 Engine Steward 的实际定位 |
| 9 | `PLAN_SIMULATOR_UPGRADE.md` 无状态标注 | S4 已回滚，`config/step_rules.yaml` 已删，第 142~200 行设计**已作废** | 顶部加实施状态表 + 作废声明 |

### 2.3 配置一致性

**发现的真实缺陷**：`web_server.py` 的 CORS 白名单**只写死 8080**，而服务默认端口是 **8081**（`argparse` 默认值 / `start.sh` / `Makefile` 三者一致为 8081）；模块 docstring 也写 8080。→ 默认端口启动时，任何跨端口调用都会被 CORS 拦掉。

| 修复 | 说明 |
|------|------|
| CORS 白名单**跟随 `PORT` 环境变量**（默认 8081），并保留历史端口 8080 | `web_server.py` |
| 模块 docstring 端口同步为 8081 | `web_server.py` |
| **新增守护测试**：断言白名单必须覆盖服务默认端口 | `tests/test_cors_config.py`（+15 行） |
| 新增 `config/agent_llm_config.json.example`（此前 LLM 配置无模板，而 storage 有） | 新文件 |
| `setup.sh` 改为以该 `.example` 为 schema **单一来源**，消除第二处 schema 定义 | `setup.sh` |
| `.gitignore` 去重：7 条整段重复、`*.xlsx` ×2、`.codegraph` 双写；删无效的 `.git/*`；补 `output/` | `.gitignore` |

### 2.4 Coze 残骸清理（B 路径已声明移除，残骸仍在）

| 删除对象 | 依据 |
|----------|------|
| `src/agents/`、`src/graphs/`、`src/graphs/nodes/`、`src/storage/s3/`、`src/storage/database/`、`src/storage/database/shared/`、`src/utils/`、`src/utils/file/` | 全部 `__init__.py` 为 0 字节且零引用 |
| `src/utils/file/file.py` | 325 行死代码；顶层 import `pptx`/`chardet`，二者只在 `coze-platform` extra（B 路径） |
| `.coze/`、`src/checkpoint.py`、`web_server_v2.py` | `web_server_v2.py` 1358 行、全仓零引用、且**本身无法运行**（用了未定义的 `app`） |
| `scripts/{http_run,load_env,load_env,local_run,pack,setup}.sh` | Coze 专用（`coze_workload_identity` / `COZE_*` 环境变量） |
| `local_test.py` | README 承诺但必然 ImportError 的冒烟脚本 |
| 根级 `web_server.log`（2026-07-14，35 KB） | 旧日志路径名残留；现由 `logs/` 承载 |

**合计**：30 文件、**+250 / −2242 行**。

---

## 三、端到端实证（真起服务，非静态推断）

```
make smoke                          → smoke_ok 0.1.0 mimo-v2.5-pro
./start.sh                          → 7 秒内就绪
GET /health                         → status=ok  version=0.1.0  llm_configured=true
                                      store_backend=PostgresStore   ← 持久化，未降级到内存
POST /chat（牛肉面店 客单价18元）    → intent=quick_scan
                                      monthly_revenue = [推算] 从客流×单价×30天
                                      monthly_fixed_cost = [用户] 组件求和(租金[用户])
```

来源标注（`[用户]/[推算]/[缺失]`）在真实响应中正确产出，置信层契约成立。

---

## 四、新发现的真实缺陷（**未修改**，需你定夺）

### 4.1 🔴 抽取器措辞覆盖率缺口（影响产品核心体验）

> **2026-09-12 21:40 更正**：本节初版有 2 处结论错误，已按实跑复核修正（用完整参数 + `derive()` +
> `quick_scan` 三层验证，而非只打印单个字段）：
> · 初版称「`毛利率60%` → None，未做换算」——**错误**。实测它产出 `gross_margin=0.6`，
>   引擎正确反推出 `variable_cost_ratio=0.4`，端到端月利润 22000 正确。属**误判**。
> · 初版称「`食材成本占4成` → None（未识别）」——**不准确**。实测它**静默产出 `0.04`（差 10 倍）**，
>   比"不识别"严重得多。

实测矩阵 —— 同一语义、不同措辞：

| 输入措辞 | 实测结果 | 判定 |
|----------|----------|------|
| `变动成本率40%` | `variable_cost_ratio = 0.4` | ✅ |
| `变动成本率0.4` | `0.4` | ✅ |
| `成本率40%` | `0.4` | ✅ |
| `食材成本占营业额40%` | `0.4` | ✅（但要求**显式对象词**） |
| **`食材成本占40%`**（口语省略对象词） | **None** | ❌ 漏抽 —— 餐饮最自然的说法 |
| **`食材成本占4成`** | **`0.04`** | 🔴 **静默算错 10 倍**（「4」被当 4% 归一化） |
| **`毛利率六成`** | **`variable_cost_ratio = 0.94`** | 🔴 **静默算错**（「六」被当 6%） |
| `毛利率60%` | `gross_margin = 0.6` → vcr `0.4` | ✅（初版误判，已更正） |

| 输入措辞 | 实测结果 | 判定 |
|----------|----------|------|
| `客单价18元` | `price_per_unit = 18.0` | ✅ |
| **`每碗18元` / `每杯18元` / `每份18元` / `每位60元`** | **None** | ❌ 量词别名全缺（碗/杯/份/位/件/瓶） |

| 输入措辞 | 实测结果 | 判定 |
|----------|----------|------|
| `月租金1万5` | **`10000`** | 🔴 **金额算错**（应为 15000，`(\d+\s*万)` 匹配到「1万」即返回，丢掉尾数） |
| `月租金一千五` / `月租金八千` / `月租金1.5万` | 1500 / 8000 / 15000 | ✅ |

**影响**：用户按日常说法描述生意（「食材成本占 4 成」「每碗 18 元」「租金 1 万 5」），
引擎要么判为缺失（覆盖率实测仅 17% → 直接进「参数不足，请补充」骨架），
要么**给出错 10 倍的数字却不报错** —— 后者更危险，用户会以为引擎"懂了"。

**另发现一处结构性隐患（非覆盖率问题）**：`gross_margin` 的单位在
`param_guard`（归一为 0~1）/ `field_model`（按 0~100 处理）/ `workflow_engine`
（`>=50` 阈值按 0~100；输入侧用 `gm/100 if gm>1 else gm` 猜单位）**三处两种口径**。
主管线靠"猜单位"那行勉强正确，但按 `field_model.derive()` 的公开契约
（其 docstring 明说「给定输入字段集含缺失 None」）直接传入原始输入时，会得到
`derive({"gross_margin":0.6})["variable_cost_ratio"] = 0.994`（应为 0.4）。

**修法**（完整方案见 `PLAN_EXTRACTOR_PIPELINE_FIX_2026-09-12.md`）：
1. 中文分数：`X成` → `X × 0.1`，并绑定语义前置词（避免误伤「完成/成员」）。
2. 量词别名：以**独立正则**处理 `每(碗|杯|份|位|件|瓶) + 数字 + 元`，数字后必须跟元/块
   —— 从结构上排除「每份**成本**7元」被误当售价。
3. 成本占比对象词改为可选 + 负向断言排除「固定成本/总成本」。
4. `_parse_number` 支持 `A万B` 缩写（`1万5` → 15000）。
5. 统一 `gross_margin` 单位为 0~1，删除 `gm/100 if gm>1 else gm` 的单位猜测。

> 这正是你 roadmap 里的「抽取器精度」根因项，需以**措辞矩阵 oracle** 形式落地
> （每条措辞一个断言 + 每类误抽一个反例断言），避免再漂。

### 4.2 🟡 CORS 的已知边界（已注释，非缺陷）

CORS 白名单跟随 **`PORT` 环境变量**。若用 CLI 直接 `web_server.py -p 9000`（不走 `start.sh`），`PORT` 未设置 → 白名单仍是 8081/8080。已在代码注释中显式标注。若需彻底解决，应把白名单构建挪到 `argparse` 解析之后。

### 4.3 🟡 根级产物残留

`output/model_project.xlsx`、`reports/*.md`（2026-07-10 / 07-13 两份审计报告）仍在工作区物理存在。均已被 `.gitignore` 覆盖（**未进版本库**），不影响交付，仅为整洁度。

---

## 五、曾怀疑但**已排除**的问题（避免后人重复怀疑）

| 疑似问题 | 核查结论 | 证据 |
|----------|----------|------|
| `test_p49` 在新克隆（配置为空）时必挂 | ❌ **不是问题** | `get_model_name()` 用 `dict.get("model", default)`，**空串不触发默认值** → 返回 `""`；测试同源比较 `"" == ""` 通过；且测试 613 行已有 `if model:` 护栏跳过硬编码检查 |
| 文档里的 `agents.agent` / `src/main.py` 引用是死引用 | ❌ **不是问题** | 全部位于「该路径已移除」的历史说明、或 `test_p48_*` 守护断言中，属合法语境 |
| `PLAN_SIMULATOR_UPGRADE.md` 的 S1/S2/S3/S5 是否也没落地 | ❌ **不是问题** | 代码实证：`_revenue_series`(workflow_engine.py:349)、`_npv_raw/_irr_raw`(:863-868)、`dynamic_runway`(:876-890)、`trend_comparison`(:1556) |
| README 写死模型名导致换模型漂移 | ❌ **已自愈** | README 现明确「不写死具体模型名」，实际值只从 `config/agent_llm_config.json` 读 |

---

## 六、剩余待决策（按优先级，**均不阻断交付**）

### P1 · 抽取器措辞覆盖（见 4.1）
产品体验最直接的短板。建议按「一个措辞一条断言」的 oracle 方式补，四条可分批独立交付。

### P1 · 文档归档（工程卫生的最大一块）
根级 **9 份 .md 共约 181 KB**，混杂三种性质：

| 分类 | 文件 | 建议 |
|------|------|------|
| 长期有效（设计基线） | `ARCHITECTURE.md`(26K)、`CALCULATION_PHILOSOPHY.md`(12K)、`ENGINEERING_DESIGN.md`(42K)、`AGENT.md`(3K) | 移入 `docs/`，README 加索引 |
| 已完成/已作废的计划 | `PLAN.md`(34K)、`PLAN_CALCULATION_FLOW_REFACTOR.md`(29K)、`PLAN_ADVISOR_PANEL.md`(19K)、`PLAN_SIMULATOR_UPGRADE.md`(10K，S4 已回滚) | 移入 `docs/archive/`，各加一行完成状态 |
| 过程记录 | `CLEANUP_CHECKLIST.md`(9K) | 同上，归档 |
| 交付入口 | `README.md`(13K) | **保留在根目录** |

**我未擅自移动**——移动 9 个文件会改变仓库结构，且这些文档互相引用，建议你确认后再做。

### P2 · `.venv` 可移植性
当前 `.venv` 软链到 WPS 灵犀的 Python（`.../WPS 灵犀/python-env/bin/python3.12`）。WPS 一旦卸载/升级，环境即崩。建议重建为项目内独立 venv（`uv sync` 默认行为）。

### P2 · 推送远程
`main` 现**领先 `origin/main` 6 个提交**；`baseline` 分支也只在本地。
- 需要注意：本机到 `github.com:443` 长期 502，此前是靠 **GitHub Git Data API**（只通 `api.github.com`）推送并保持 SHA 逐字节一致的。

---

## 七、验收断言（可复跑）

```bash
# 1) 门禁：0 failed
make test                                   # 期望 355 passed, 0 failed

# 2) 后备口径与门禁对齐：331 + 24 = 355
.venv/bin/python3 tests/run_all.py          # 期望 331 passed, 0 failed, 24 skipped

# 3) 无死代码 / 残骸
git ls-files | grep -cE 'web_server_v2|local_test|src/agents/|src/graphs/'   # 期望 0

# 4) .gitignore 无重复条目
sort .gitignore | uniq -d | grep -v '^$'    # 期望空

# 5) 配置模板存在且未被误忽略
git check-ignore -q config/agent_llm_config.json.example && echo FAIL || echo OK   # 期望 OK

# 6) 端到端
make smoke                                  # 期望 smoke_ok <version> <model>
./start.sh & curl -s --noproxy '*' http://127.0.0.1:8081/health   # 期望 status=ok
```

---

## 八、附：本次审计中发现的操作风险（自省）

用工具批量修改**同一个文件**时，若把多个编辑并发下发，会发生「读-改-写」竞争导致**部分修改被静默覆盖**（本次 README 首轮 5 处修改只落地 1 处，编辑工具仍逐条回显成功）。
→ **对策：对同一文件的多次修改必须串行，或改为一次性整体写入。** 本文件所记录的 README 修正已按此方式重做并逐条核验。
