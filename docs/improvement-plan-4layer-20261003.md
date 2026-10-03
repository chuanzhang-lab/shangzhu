# 创业者工作台（shangzhu）完整改进计划 — 四层防线

- 日期：2026-10-03
- 依据：code-improvement-plan 技能六阶段流程（调查 → 环境 → 计划 → 设计 → 模块 → 审计）
- 性质：本计划为「完整改进计划」交付物，**未动任何代码**；实施前需按第 8 节顺序逐模块确认。

---

## 1. 背景与目标

- **项目概述**：创业者财务分析工作台（FastAPI + 原生 JS 单页 + PostgresStore 持久化），本地独立运行（端口 8081）。项目根：`/Users/newmacbook/Desktop/shangyezhushou/shangzhu/`。
- **本次目标**：针对 2026-10-01 前端 i18n 翻译函数遮蔽事故暴露的 4 类系统性问题（旧代码继续跑 / 静默失败 / 无门禁 / 测试盲区），建立四层防线，使**同类问题不可能静默复发**：
  1. 运行态自证（版本握手 + 错误上报）；
  2. 静默失败治理（异常不吞、降级必有痕）；
  3. 门禁（lint + 护栏测试 + CI）；
  4. 测试盲区（测试库隔离 + 浏览器 e2e + 双副本治理）。
- **范围一句话**：只改 `shangzhu/` 本体；`shangzhu-en/` 仅作修复来源参照与 drift 对比对象（见第 5 节边界例外）。

## 2. 现状总结

### 2.1 代码现状（阶段一调查，2026-10-03 只读实测）

| 项 | 实测结果 |
|---|---|
| 技术栈 | Python 3.12（.venv 3.12.13）、FastAPI + uvicorn、langchain/langgraph 1.x、psycopg3、原生 JS 单文件前端（app.js 1071 行）+ app.css |
| 结构 | `web_server.py`（1624 行，含 CHAT_HTML 模板）+ `src/`（router/storage/tools/advisor 等 15 个 py 模块）+ `src/web_static/`（app.js/app.css）+ `tests/`（38 文件） |
| 测试 | pytest 收集 **451** 个用例（shangzhu）；同构副本 shangzhu-en 632 个。护栏测试仅 2 个（test_param_guard、test_persistence_guard），EN 副本有 7 个 |
| 门禁 | Makefile 有 sync/test/smoke/compile 四目标，**无 lint**；无 `.github/`、无 ESLint、无 pre-commit（git remote 存在：github.com/chuanzhang-lab/shangzhu.git） |
| 前端 | 7 处 `catch (e)` 一律吞成 toast；`switchTask(...)` 3 处调用未 await/未 catch（app.js:158/164/170）；`?v=20260413a` **写死**于 web_server.py:809/883，无 Cache-Control 中间件 |
| 后端 | `except Exception` 共 **54** 处（web_server.py 17 + src/ 37），无统一审计口径 |
| 文档 | README/AGENT.md 齐全（AGENT.md 69 行）；**无**「降级必有痕 / 异常不吞 / 每事故一护栏」公约条款 |
| Git | 工作区干净，最近提交为 security/i18n 文档与数据修复 |

### 2.2 环境现状（阶段二调查）

| 项 | 实测结果 |
|---|---|
| 运行时 | .venv Python 3.12.13 ✓（requires-python >=3.12）；uv 可用；Node v26.0.0 ✓ |
| 外部服务 | 本机 PostgreSQL（PostgresStore 实连，任务表 **639** 条（未软删 78）、消息 **1455** 条，其中 `"New task"` 测试残留 **98** 条，单秒批量峰值 **42** 条（2026-10-01 15:10:38），时间跨度 10-01 → 10-03 **仍在增长**）；降级链 PostgresStore → LocalFileStore → MemoryStore。**⚠️ 两仓共用同一库**：`_db_url()` 三级优先级为 env `PGDATABASE_URL` → `config/storage.json` → 内置默认，实测两仓 env 均未设置、`storage.json` 均不存在，双双落到内置默认 `postgresql://newmacbook@localhost:5432/shangzhu`；本机 PG 仅有 `fangan1` / `postgres` / `shangzhu` 三个库，**无 `shangzhu_en`** |
| 浏览器 e2e | npx playwright 1.63.0 CLI ✓，但 **chromium 浏览器二进制未安装**（ms-playwright 缓存为空）；playwright Python 包未装 |
| ESLint | **未安装**（node_modules 不存在），需一次性 `npm i -D eslint` |
| 测试隔离 | 无 `tests/conftest.py`；全 tests 无任何 `LOCAL_STORE_PATH`/`PGDATABASE_URL` 覆盖 → 测试直写真实 PG |

### 2.3 核心结论（对原方案的 4 处实测纠正）

1. **原 P0「shangzhu 有完全一样的必爆翻译遮蔽 bug」不成立**：shangzhu 无 i18n、app.js 无全局翻译函数 `t()`（grep 无 `t('...')` 调用），`tasks.forEach(t => …)` 在当前代码里不会炸。真实风险降级为「命名遮蔽隐患」（若未来引入 i18n 即复发；`taskMenu` 内 `const input` 遮蔽全局 `input` 同理）。**但缓存问题实锤**：`?v=20260413a` 写死 + 无缓存中间件，与 EN 修复前完全一致。
2. **「632 个用例」是 shangzhu-en 的数**，shangzhu 本体 451 个；两副本合计 1083，双倍维护成本已成事实。
3. **`except Exception` 不是 18 处而是 54 处**（web_server 17 + src 37），审计面比原估大 3 倍。
4. **测试污染实锤且比描述更重**（2026-10-03 23:00 复核刷新）：任务表全量 **639** 条（`deleted_at IS NULL` 仅 78 条 —— 原「78」是未软删口径，**低估了 8 倍**），消息 **1455** 条；`"New task"` 残留 **98** 条，单秒批量峰值 **42** 条（原记 20 条），跨度 2026-10-01 15:10 → 2026-10-03 11:59 —— **污染是持续发生的，不是一次性残留**。`test_task_api.py` 直接 `get_store()` 走真实 PG 无清理。
   → **对实施顺序的修正**：M-00（清理）与 M-01（隔离）不可分先后串行执行「先清后隔」——只清不隔离，下次跑测试立刻涨回来。正确顺序是 **M-01 隔离先行 → 隔离生效后跑一次 M-00 清理 → 此后永久免做**。
5. **【补充纠正 5】两仓共用同一个 PG 数据库**（原方案未提及，2026-10-03 23:20 实测）：数据库**不属于仓库**（本机 `localhost:5432` 的外部状态，仅有 `fangan1`/`postgres`/`shangzhu` 三库，**没有 `shangzhu_en`**）。两仓 `_db_url()` 的内置默认**完全相同**，且 env、`config/storage.json` 两级均未配置 → 双双落到同一个 `shangzhu` 库。
   → 影响：**639 条污染是两仓测试叠加写出来的**。M-01 若只隔离 shangzhu 一仓，EN 跑 632 个测试仍会灌库，MS1 的「计数差为 0」验收必然破功。**M-01 必须跨仓同做**（或两仓各指向独立库）。
   → 另注：EN 侧已有两项 shangzhu 没有的修复可**直接移植**：`_static_ver()`（mtime 动态版本号 + `Cache-Control: no-cache` 中间件，EN web_server.py:909/923/934）与 `test_appjs_translator_shadow.py` 遮蔽护栏。这正是 M-02/M-03「移植 EN」的依据，已实测确认存在。
   → 反向提醒：EN 的 **i18n 层整改不可平移**到 shangzhu（shangzhu 无 `src/i18n`），「EN 修了就同步」不能一概而论，须判断修复落在**同源层**还是 **EN 独有层**。

## 3. 问题清单

| 编号 | 严重度 | 现象 | 位置 | 影响 |
|------|--------|------|------|------|
| P-01 | 严重 | 测试直写真实 PG，无隔离、无清理，**且两仓共用同一库** | 无 tests/conftest.py；test_task_api.py:63 `get_store()`；EN 仓 conftest 仅钉 locale | 任务表累积 **639** 条（未软删 78）、消息 1455 条，其中 `"New task"` 残留 **98** 条、单秒批量峰值 **42** 条，**仍在增长**；两仓测试互相叠加污染；测试不可重复，数据可信度受损 |
| P-02 | 严重 | 静态资源版本号写死 `?v=20260413a`，无 Cache-Control 中间件 | web_server.py:809/883；app.js/app.css 走 StaticFiles | 改了前端代码用户浏览器仍跑旧 JS——本次事故「旧代码继续跑」的直接成因 |
| P-03 | 严重 | 无任何自动门禁（lint/CI/pre-commit 均无） | 仓库级；Makefile 无 lint 目标 | 同类 bug 可长驱直入主干，451 用例全靠手敲 `make test` |
| P-04 | 一般 | 变量/参数遮蔽全局名（`t` 遮蔽未来的翻译函数、taskMenu 内 `input` 遮蔽全局 input） | app.js:153 等 5 处 `t`；app.js:255/259 `input` | 当前不炸但属事故复发温床；EN 有护栏测试 shangzhu 没有 |
| P-05 | 一般 | 前端静默失败面大：7 处 catch-all 吞错转 toast；3 处 switchTask 未 await/未 catch | app.js 全文；:158/164/170 | 运行期错误无痕，排查全靠口述 |
| P-06 | 一般 | 前端错误无法被服务端观测（无 /client-log） | web_server.py 无该端点 | 「用户看到了什么」服务端不可查 |
| P-07 | 一般 | /health 无 build 号/commit，前端无版本握手 | web_server.py:916 health() | 长开标签页场景缓存策略管不到，旧页面无从自证 |
| P-08 | 一般 | 54 处 `except Exception` 无统一口径（故意降级/吞掉/不该捕获混杂） | web_server.py 17 + src/ 37 | 排查盲区，安全审查口径不一 |
| P-09 | 一般 | 静态扫描测不出运行期 TypeError，无浏览器 e2e | tests/ 全部为 Python 单测；make smoke 仅导入级 | 本次事故恰是运行期才炸，测试全绿仍上线 |
| P-10 | 严重 | 双副本（shangzhu 451 用例 / shangzhu-en 632 用例）漂移治理缺失：**EN 修了 shangzhu 没修，且两仓共用同一 PG 库** | shangzhu/ 与 shangzhu-en/；`_db_url()` 两仓内置默认均为 `postgresql://newmacbook@localhost:5432/shangzhu` | 同一 bug 两个产品各犯一次；测试污染跨仓叠加（639 条是两仓合灌的） |
| P-11 | 轻微 | AGENT.md 无「降级必有痕/异常不吞/每事故一护栏」公约；README 无排障口诀 | AGENT.md（69 行）/ README.md | 好实践只靠个别模块自觉，无法代际传承 |

严重度定义按技能模板：致命=无法运行/数据丢失；严重=核心功能错误或明显安全/性能问题；一般=功能缺陷/可维护性；轻微=风格/文档。

## 4. 改进范围与目标

**要做的（11 项，对应问题清单）：**

1. 测试库隔离（conftest.py 强制隔离）→ 测试可重复、不碰真实数据（P-01）
2. 缓存修复移植（mtime `?v=` + Cache-Control 中间件，参照 EN 已验证方案）→ 旧代码不可能静默继续跑（P-02）
3. 门禁（ESLint + make lint + pre-commit + GitHub Actions）→ 同类 bug 进不了主干（P-03）
4. 遮蔽命名治理（t→task、input→el）+ 护栏测试移植（P-04）
5. 前端 catch 统一「阶段 + 错误码」模板、未 await 的 switchTask 补 catch（P-05）
6. /client-log 端点 + sendBeacon 上报（P-06）
7. 版本握手：/health 返回 build 号 + git commit，前端不一致弹横幅（P-07）
8. 54 处 except 三档审计（P-08）
9. 浏览器 e2e 冒烟进 make smoke（P-09）
10. 双副本治理：三分支决策（P-10，见 7 节 M-09）
11. AGENT.md 公约 + README 排障口诀（P-11）

**完成标准**：每个模块见第 7 节验收栏；总体见第 10 节。

**明确不做**：不做业务功能变更；不重构 web_server.py 拆分（1624 行单文件是既有架构，拆分另立计划）；不改 LLM 链路；不升级依赖大版本；不引入 TS/打包工具链（保持原生 JS 单文件）；不动 shangzhu2.zip 归档。

## 5. 项目边界声明

- **范围内**：`shangzhu/` 目录内全部代码、配置、测试、文档、依赖声明（含新增 package.json/ESLint 配置、.github/workflows/、tests/conftest.py）。
- **范围外（不修改）**：
  - `shangzhu-en/`（同构副本）——**边界例外**：M-02/M-03/M-05 只做「从 EN 移植到 shangzhu」的单向搬运；M-09 的 drift 护栏测试只**读取** EN 做 hash 对比，不写。合并/归档 EN 需用户另行决策后单独立项。
  - `shangzhu2.zip`、系统配置、全局 npm/uv 配置、第三方库源码、本机 PostgreSQL 服务本身（仅以配置声明连接）。
- 依据：boundary-rules.md；例外按第 5 节规则显式列出并说明理由（EN 是修复事实来源，不读无法搬运）。

## 6. 改进设计（十维度）

### 6.1 架构设计
- 四层防线分层明确：运行态自证（L1）→ 静默失败治理（L2）→ 门禁（L3）→ 测试盲区（L4），依赖方向 L3/L4 保障 L1/L2 的代码质量。
- 版本握手复用 EN 已验证的 `_static_ver()`（mtime 整秒）机制，不发明新机制；在其上追加 git commit 读取（`git rev-parse --short HEAD`，失败降级为 "unknown"）。
- 落点：web_server.py（中间件 + /health + /client-log）、src/web_static/app.js（横幅 + 上报）、tests/（护栏族）。

### 6.2 功能设计
1. **版本握手**：`/health` 返回新增 `static_ver`（app.js mtime 版本号）与 `commit`。前端 fetch('/health')（加载后一次 + 每次 catch 错误时）比对自身 `__STATIC_VER__`（注入 app.js 尾部的常量），不一致 → 顶部横幅「页面版本过旧，请刷新（Ctrl/Cmd+Shift+R）」。
2. **前端错误上报**：统一 `reportClientError(stage, code, message)` 函数——`console.error('[失败于[stage:code]]', e)` + `navigator.sendBeacon('/client-log', …)`。7 处 catch 与 3 处未 await 的 switchTask 全部走它。
3. **/client-log**：POST JSON `{stage, code, message, page_ver, ts}`；服务端原样落 `logs/web_server.log`（WEBCLIENT 标签）。
4. **e2e 冒烟**：playwright（node，npx 现成）脚本：加载页面 → 点新建任务 → 断言无 toast 报错、无 console error、/tasks 写入走**测试库**。
5. **lint**：ESLint `no-shadow`/`no-undef` 为错误级；`t`/`input` 遮蔽点先手工改名再上面状规则。

### 6.3 数据设计
- 测试隔离三闸（conftest.py）：`LOCAL_STORE_PATH=<tmp>`、`PGDATABASE_URL` 强制指向测试库 `shangzhu_test`（不存在则整库 `LocalFileStore` 降级跑，绝不出本机真实库）、`sys.path` 与 pyproject pythonpath 保持一致。
- 测试残留清理脚本 `scripts/clean_test_tasks.py`：按名称模式（`New task`/`xhr-task`/`测试`）+ 创建时间聚类识别测试残留，**dry-run 默认**，`--apply` 才删（软删）。
- /client-log 落盘仅追加到现有 logs/ 轮转体系（10MB×5），不建新表。

### 6.4 接口设计
- `/health`：现有字段不动，**新增** `static_ver`、`commit`（向后兼容，test_health_reports_store_backend 等旧断言不破坏）。
- `POST /client-log`：入参 body 限 2KB、字段白名单（stage/code/message/page_ver/ts）、message 截断 500 字符、拒绝非 JSON → 400。响应恒 `{"ok":true}`（上报端点不给前端制造二次错误）。
- 前端内部接口：`reportClientError(stage, code, err)`、`checkVersionHandshake()`，单一出口。

### 6.5 性能设计
- 缓存语义：`/static/*` 与 `/i18n.js`（若引入）`Cache-Control: no-cache`（回源校验 304，命中 ETag 不重传）；HTML 本身 no-cache（EN 已有注释教训：旧外壳指向旧 ?v=）。
- /client-log 节流：同 (stage,code) 60 秒内最多 1 条，防错误风暴打爆日志。
- /health 增加的 git commit 读取做进程内缓存（启动时读一次即可，commit 不热变）。

### 6.6 安全设计
- /client-log 防滥用：体积/字段白名单/截断/节流（见 6.4/6.5）；不接受堆栈中的任意长文本，不回显。
- 不引入任何新密钥/凭证；PG 连接继续走现有 `PGDATABASE_URL`/config/storage.json 单源。
- ESLint `no-undef` 顺带封掉意外全局泄漏。

### 6.7 可维护性设计
- AGENT.md 新增公约三条：**降级必有痕**（except 降级必须 WARNING）、**异常不吞**（catch-all 必须 console.error + reportClientError）、**每事故一护栏**（每起事故固化一条护栏测试，命名 `test_*_guard` 或 `test_*_shadow`）。
- 命名规范：JS 任务对象参数一律 `task`，DOM 局部变量一律避开全局名（input/empty/chat 等）。
- catch 模板统一：`catch (e) { reportClientError('<阶段>', '<错误码>', e); setToast(...) }`，阶段枚举：loadTasks/switchTask/saveParams/chat/delete/rename。

### 6.8 可靠性设计
- 54 处 `except Exception` 三档处置：A 故意降级（保留 + 补 WARNING，参照 storage「降级必有痕」）、B 吞掉（补日志/上报）、C 不该捕获（收窄异常类型或删除）。产出审计表逐条标注档位。
- 版本握手本身可靠性：/health 不可达时前端**不报错不横幅**（握手失败静默跳过，避免次生噪音）。
- 缓存修复回退：`_static_ver` 读不到文件返回 "0"，绝不吐占位符字面量（EN 已有此防御，原样保留）。

### 6.9 可测试性设计
- 护栏测试族（静态扫描，不执行 JS）：移植 EN 的 `test_appjs_translator_shadow`、`test_static_cache_guard`；新增 `test_no_unawaited_switchtask`（扫描 switchTask 调用点必须带 .catch/await/void+catch）、`test_client_log_contract`（端点契约 + 节流）、`test_health_version_fields`。
- e2e 断言与 Python 单测分层：`make test`（451+ 用例）→ `make lint` → `make smoke`（导入级）→ `make e2e`（浏览器级）。
- conftest 隔离后所有测试可重复跑且互不污染。

### 6.10 兼容与部署设计
- 版本握手 + mtime ?v= 双保险：短开标签页靠缓存失效，长开标签页靠握手横幅，两层互补。
- 部署即 `./start.sh`（无独立部署流程）；启动横幅追加一行「升级后请硬刷新（Cmd+Shift+R）」（一行 echo，随 M-02 落地）。
- 回滚：每模块独立 commit，`git revert` 单模块即可回退；ESLint/pre-commit 配置出问题可 `SKIP=…` 或删除配置文件回退，不影响运行时。

## 7. 流程模块拆解

| 模块 | 目标 | 前置 | 具体动作 | 验收标准 | 回退 |
|------|------|------|---------|---------|------|
| M-00 | 立即止血（不改代码逻辑） | 无 | ① `scripts/clean_test_tasks.py` dry-run 确认后 --apply 清测试残留；② README 排障口诀（先看 logs/web_server.log + console `[失败于[…]]`） | 任务列表无 `"New task"`/xhr-task 残留；README 段落入库 | 残留是软删，可恢复 |
| M-01 | 测试库隔离（**跨仓同做**） | 无 | 新建 tests/conftest.py：强制 LOCAL_STORE_PATH=tmp、PGDATABASE_URL→shangzhu_test 或整库降级 LocalFileStore；test_task_api.py:63 的直接 get_store() 收敛到 fixture。**EN 仓同步补**：其 tests/conftest.py 已存在但只钉 `SHANGZHU_LOCALE=zh`，无存储隔离，须追加同一套隔离（或两仓各指向独立库 `shangzhu_test` / `shangzhu_en_test`） | **两仓各跑一次 `make test`，真实库任务计数均不变**（只做一仓 = 另一仓跑测试照样灌库，验收必然破功） | 删除 conftest.py 即回退 |
| M-02 | 缓存修复（移植 EN） | M-01 | web_server.py：`_static_ver()` + `Cache-Control: no-cache` 中间件 + CHAT_HTML 占位符注入，替换写死 `?v=20260413a`；start.sh 横幅加「升级后硬刷新」；移植 test_static_cache_guard | 改 app.js 任一字节 → 重载页面拿到新 ?v=；curl -I /static/app.js 显示 no-cache；护栏测试绿 | git revert 单 commit |
| M-03 | 遮蔽治理 + 护栏 | M-02 | app.js：5 处 `t`→`task`、taskMenu 内 `input`→`renameInput`；移植 test_appjs_translator_shadow（参数适配）；加 ESLint（no-shadow/no-undef）+ `make lint` | make lint 0 error；`make test` 绿；遮蔽护栏绿 | revert；ESLint 配置可单独删 |
| M-04 | 静默失败治理 | M-03 | 7 处 catch 换统一模板（阶段+错误码+reportClientError）；app.js:158/164/170 补 .catch；新增 test_no_unawaited_switchtask | 静态护栏绿；e2e 冒烟中人为触发错误可见 `[失败于[…]]` 且落 logs/web_server.log | revert |
| M-05 | 版本握手 | M-02 | /health 加 static_ver + commit；app.js 加 checkVersionHandshake() 横幅；新增 test_health_version_fields | 手工改 app.js 不重启 → 横幅出现；/health 返回 commit 与 `git rev-parse --short HEAD` 一致 | revert |
| M-06 | /client-log 上报 | M-04, M-05 | web_server.py 加端点（白名单/2KB/截断/节流）；reportClientError 接 sendBeacon；新增 test_client_log_contract | curl POST 超限→400；正常→logs/web_server.log 有 WEBCLIENT 行；节流 60s 生效 | revert |
| M-07 | CI 门禁 | M-03 | `.github/workflows/ci.yml`（make compile + lint + test 三件套）；本地 git pre-commit 跑同样三件套（仓库已有 GitHub remote，CI 直接可用） | push 后 Actions 绿；本地 commit 被拦截测试可复现 | 删 workflow/钩子即回退 |
| M-08 | 浏览器 e2e | M-01, M-02 | `npx playwright install chromium`（一次性，缓存于系统目录，属范围外依赖安装动作）；tests/e2e/smoke.mjs：加载→新建→断言无 toast/console error；`make e2e` | make e2e 绿；故意注入 TypeError → e2e 红 | 删目录+Makefile 目标 |
| M-09 | 双副本治理 | M-02..M-05 | 三分支**待用户决策**：A 归档 shangzhu-en；B drift 护栏（test_copy_drift：关键文件 hash 对比，仅读 EN）；C 合并为单代码库 + SHANGZHU_LOCALE（工作量大，另立项）。默认先落 B | 若 B：护栏测试绿，EN 侧再改关键文件时 shangzhu 测试红 | B 可单独 revert |
| M-10 | 公约固化 | M-04 | AGENT.md 加三公约（降级必有痕/异常不吞/每事故一护栏）+ 排障口诀；54 处 except 三档审计表落 docs/ | 审计表 54 行逐条有档位；AGENT.md 公约段落入库 | 文档 revert |

## 8. 实施步骤与里程碑

**顺序**：**M-01 → M-00** → M-02 → M-03 → M-04 → M-05 → M-06 → M-07 → M-08 → M-09（决策后）→ M-10（可与 M-06..M-08 并行）。

> ⚠️ **顺序修正（2026-10-03 23:00 复核）**：原写 M-00 → M-01（先清残留、后加隔离）。实测污染是**持续发生**的（639 条且跨三天仍在涨），先清后隔等于「清完即被重新污染」。
> 正确顺序：**M-01 conftest 隔离先行** → 隔离生效后跑一次 **M-00 清理**（一次性，清完即止）→ 此后永久免做。

**里程碑**：
- **MS1 数据可信（P0）**：**M-01 先行，M-00 其后** — 交付：conftest 隔离 + 残留清零。评审点：跑两次 `make test` 真实库计数**差为 0**（639 不再增长）。
- **MS2 旧代码不再静默跑（P0/P1）**：M-02 + M-05 — 交付：缓存修复 + 版本握手。评审点：改 app.js 触发横幅演示。
- **MS3 同类 bug 进不了主干（P1）**：M-03 + M-07 + M-08 — 交付：lint + CI + e2e。评审点：人为提交一个遮蔽变量，pre-commit/CI 拦截演示。
- **MS4 观测与整洁（P2）**：M-04 + M-06 + M-09 + M-10 — 交付：错误上报链路 + 双副本决策落地 + 公约/审计表。评审点：服务端日志能查到前端错误现场。

**关键路径**：M-01 → M-02 → M-03 → M-07 → M-08（测试隔离是所有验证的地基；ESLint 落地后 CI 才有意义；e2e 依赖稳定的测试数据环境）。阻塞项：M-09 等双副本决策；M-08 依赖 playwright chromium 一次性下载。

**原方案「不动代码现在就能做」的归置**：①排 shangzhu 修复 → 本计划 M-02/M-03；②跑完测试手清残留 → M-00（且 M-01 落地后永久免做）；③排障口诀进 README → M-00；④重启后硬刷习惯 → M-02 的 start.sh 横幅提示。

## 9. 风险与依赖

| 风险/依赖 | 类型 | 影响 | 应对 |
|----------|------|------|------|
| 双副本决策未定 | 进度 | M-09 阻塞 | 默认先落 drift 护栏（B），归档/合并后补 |
| playwright chromium 需外网下载 | 外部 | M-08 延后 | 下载一次入系统缓存；失败则 M-08 降级为 CDP 脚本（node 现成） |
| 测试库 shangzhu_test 需一次性 CREATE DATABASE | 外部 | M-01 方案二选一 | 无权限时直接整库降级 LocalFileStore 跑，零外部依赖 |
| conftest 隔离可能暴露「靠真实数据才过」的用例 | 技术 | M-01 红灯 | 逐条修用例（属预期收益，工作量预估 <10 条） |
| M-00 清理误删真实数据 | 数据 | 高（不可逆） | **M-00必须先出 dry-run 报告**按「name='New task' + 同秒批量 + 无消息」三条特征筛；软删而非物理删；清理前 `pg_dump` 留档 |
| except 三档审计 54 处工作量被低估 | 进度 | M-10 拖尾 | web_server.py 17 处先行，src/ 37 处按模块分批 |
| GitHub Actions 分钟数/网络 | 外部 | CI 不稳定 | pre-commit 本地门禁兜底，CI 失败不阻塞本地流程 |
| ESLint 对 1071 行存量 JS 报大量存量告警 | 技术 | M-03 阻塞 | 先 error 级只开 no-shadow/no-undef 两条，其余 warn 不阻塞 |

## 10. 验收标准

**总体**：`make compile`、`make lint`、`make test`（451+ 用例）、`make smoke`、`make e2e` 五件套全绿；真实 PG 任务数在连续两次全量测试后不变；无致命/严重问题遗留；第 3 节 P-01..P-11 逐条关闭。

**分里程碑**：
- MS1：`make test` ×2，PG 任务计数差为 0；测试残留清零（M-00 dry-run 报告留档）。
- MS2：修改 app.js 任一字节后浏览器自动拿到新 ?v=；旧标签页出现过期横幅；`/health` 含 static_ver/commit。
- MS3：人为制造 `t` 遮蔽 → `make lint` 红 + 护栏测试红 + CI 红（三层都拦）；e2e 注入 TypeError → make e2e 红。
- MS4：前端人为报错 → `logs/web_server.log` 可见 WEBCLIENT 行；except 审计表 54 行档位齐全；AGENT.md 三公约入库。

**验收方式**：每模块验收栏所列命令实际执行留档；MS3 的「人为制造缺陷再拦截」为必做负向测试。

## 11. 审计安排

- **时机**：全部模块完成后（MS4 评审点），对 M-02..M-08 改动代码做阶段六审计。
- **六大维度**（按 audit-checklist.md）：
  1. 代码错误纠正：新增中间件/端点/JS 函数的语法与运行时错误、边界（/client-log 超限、_static_ver 文件缺失）；
  2. 逻辑修正：节流逻辑、版本比对逻辑、conftest 隔离逻辑的边界条件；
  3. 模块间冲突：/health 新字段与旧断言、reportClientError 与既有 catch、conftest 与 451 用例的隐式数据依赖、双副本接口语义一致性；
  4. 运行改进：no-cache 带宽、/client-log 日志量、握手请求频率；对照第 2.2 节环境差距清单确认清零；
  5. 功能边界：前端上报不越界到业务接口、护栏测试只读不写、EN 副本零写入；
  6. 工程完整性：package.json/lock 齐全、CI 可复现、文档与代码一致、临时文件清零。
- **产出**：`docs/audit-report-<date>.md`，逐维度列问题（位置/现象/严重度）+ 已纠正 + 遗留风险。
