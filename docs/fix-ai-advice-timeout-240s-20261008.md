# 修复方案：AI 解读超时 30s→240s + 历史恢复后按钮消失（2026-10-08）

> 依据 code-fix-completeness-audit v2.0 七步产出。实施前过 ⑦.1，实施后过 ⑦.2（结果见文末）。
> 固定口径（用户指定）：**AI 解读超时时间 = 240 秒**。

---

### 1. AI 解读 30s 硬超时 → 240s（超时链路四处漂移）

**问题**:
- 复现（curl 计时，2026-10-08，服务 127.0.0.1:8081）：POST `/analysis/advice` 在 **30.0s** 返回
  `{"status": "timeout", ..., "reason": "解读超时，可重试"}`。日志佐证：`logs/web_server.log`
  多条 `LLM 解读跳过: 超时 30s`。当前 LLM（mimo-v2.5-pro via openrouter）生成解读常需 30s+，
  30s 预算下**必然失败**。
- 超时值四处不一致（漂移）：后端 `wait_for` 30s / LLM HTTP 客户端上限 45s / 配置文件 60s /
  前端 abort 45s。任一处低于 240s，链路都会提前断。

**项目定位与设置依据**:
- `_ADVISOR_PANEL_TIMEOUT`（web_server.py:244）：`_advise_with_timeout` 的 `asyncio.wait_for`
  预算，供「顾问面板」(:1270) 与「按需 AI 解读」(:1339) 两个用户主动触发的 LLM 解读入口共用。
  硬编码常量。主链路（用户点按钮的必经路径），失败显式返回 `status=timeout`。
- `_LLM_TIMEOUT`（src/llm_advisor.py:32）：LLM HTTP 客户端 timeout 的上限兼默认值，
  `_get_llm()`(:378-383) 里 `min(config.timeout, _LLM_TIMEOUT)` 钳制。硬编码常量。
- `config/agent_llm_config.json` `config.timeout=60`：可配置（配置单源）。
- 前端 `app.js:1027` `setTimeout(() => ctrl.abort(), 45000)`：硬编码，前端兜底 abort。
- 依据不明时的处置：N/A（每个值来源都有注释/设计口径可查）。

**关联底账**:

| # | 查询 | 范围 | 工具 | 命中 | 落点 | 类别 | 处置 |
|---|------|------|------|------|------|------|------|
| 1 | `_ADVISOR_PANEL_TIMEOUT\|_LLM_TIMEOUT\|_LLM_ADVISE_TIMEOUT\|45000` | 项目 *.py（除 node_modules） | search_files | 23 | 见下逐条 | 同类实现 | — |
| 2 | `"timeout"` / timeout 默认值 | config/、config/*.json、config/settings.py | search_files | 4 | 见下逐条 | 配置与常量 | — |
| 3 | `45000\|60000` 前端 abort | src/web_static/*.js | search_files | 3 | 见下逐条 | 引用清单 | — |
| 4 | `30 ?秒\|十几秒\|解读超时\|按需解读` | 项目 *.md、*.py 注释、app.js 文案 | search_files | 6 | 见下逐条 | 文档与测试 | — |

| 落点 | 类别 | 处置 |
|------|------|------|
| web_server.py:244 `_ADVISOR_PANEL_TIMEOUT = 30.0` | 同类实现 | **要改** → 240.0，改名 `_LLM_ADVICE_TIMEOUT`（两个入口同口径，名实一致） |
| web_server.py:1270 / :1339 引用 | 同类实现 | **要改**（随改名） |
| web_server.py:242/249 `_LLM_ADVISE_TIMEOUT = 8.0`（闲聊 steward） | 同类实现 | **有意不同**：闲聊旁路 8s 是产品口径（快问快答不等 LLM），不属本次预算 |
| src/llm_advisor.py:32 `_LLM_TIMEOUT = 45` | 同类实现 | **要改** → 250（必须 **> 240**：wait_for(240) 先赢才有干净的「解读超时」文案；若客户端先抛错，用户看到的是「解读失败」） |
| src/llm_advisor.py:217/379/381/383（clamp 逻辑引用常量） | 同类实现 | **不适用**：逻辑不变，值随 :32 |
| config/agent_llm_config.json `timeout: 60` | 配置与常量 | **要改** → 250（`min(config, cap)` 钳制下 60 会让 LLM 调用 60s 提前死） |
| config/agent_llm_config.json.example `timeout: 60` | 配置与常量 | **要改** → 250（模板同步） |
| config/settings.py:31 `_DEFAULT_CONFIG` `timeout: 60` | 配置与常量 | **要改** → 250（配置缺失时的默认模板同样不能低于预算） |
| config/agent_llm_config.json.bak `timeout: 60` | 配置与常量 | **不适用**：历史备份副本，语义就是当时的快照，不动 |
| app.js:1027 `45000`（解读按钮 abort） | 引用清单 | **要改** → 250000（240s 预算 + 10s 兜底，前端必须晚于后端 wait_for，保证用户看到后端的「解读超时，可重试」而不是前端裸 abort） |
| app.js:1084 `60000`（/chat abort，F8） | 引用清单 | **有意不同**：/chat 主流程 60s 兜底是另一条链路的既有口径，本次不动 |
| app.js:653/718 `60000`（节流窗口） | 引用清单 | **不适用**：节流时长与超时无关 |
| app.js:1025 文案「大约需要十几秒」 | 文档与测试 | **要改** → 与 240s 预算一致的文案 |
| src/llm_advisor.py:30-31 注释「顾问/按需解读 30s」 | 文档与测试 | **要改**（描述旧行为的注释） |
| web_server.py:243 注释 | 文档与测试 | **要改**（随常量改） |
| docs/*.md（except-audit 等提到按需解读） | 文档与测试 | **不适用**：均为行为描述，无超时数值命中 |
| tests/（test_web_server_robustness 等） | 文档与测试 | **不适用**：现有用例 monkeypatch 超时行为，不锁数值；本次另加数值/预算断言（见修复） |

盲区：ESLint/前端无独立常量表；`scripts/` 未见超时引用；生成代码/其他语言不适用（本仓 Python+JS）。

**代码环境**:
- 修改点：web_server.py 常量区 + 两个调用点；llm_advisor.py 常量 + 注释；config 三处 timeout；app.js 按钮 abort + 文案。
- 上游：前端「生成 AI 解读」按钮 → POST `/analysis/advice`；顾问 Tab → GET `/advisor`。
- 下游：`llm_advisor.advise` → ChatOpenAI(mimo-v2.5-pro via openrouter)。
- 测试覆盖：`test_analysis_advice_success_timeout_and_stale`（monkeypatch 模拟超时，不涉真实时长）；
  超时预算本身**无覆盖**（本次补）。

**修复**:
1. web_server.py：`_ADVISOR_PANEL_TIMEOUT = 30.0` → `_LLM_ADVICE_TIMEOUT = 240.0`，注释写明分层口径
   （闲聊 8s / 解读 240s / HTTP 客户端 250s），两个调用点随改名。
2. llm_advisor.py：`_LLM_TIMEOUT = 45` → `250`，注释同步（cap 必须 > wait_for 预算）。
3. config/agent_llm_config.json、config/agent_llm_config.json.example、config/settings.py `_DEFAULT_CONFIG`：
   `timeout` → 250。
4. app.js：解读按钮 abort `45000` → `250000`；文案「大约需要十几秒」→「正在生成解读，最长约 4 分钟」。
5. 新增测试（先红后绿）：
   - `test_advice_timeout_budget_is_240s`：断言 `_LLM_ADVICE_TIMEOUT == 240.0` 且 `llm_advisor._LLM_TIMEOUT > 240.0`（分层不变量）。
   - `test_analysis_advice_survives_slow_call`：monkeypatch llm_advise 睡 32s（>旧 30s 预算），断言 `/analysis/advice` 返回 `status=ok`。

**影响分析**:
- 现有测试：不打破（现有超时用例走 monkeypatch，不依赖 30s）。
- 正常行为：30s 内返回的调用完全不变；30s~240s 之间的慢调用从「必失败」变为「能完成」（本次目的）。
- 新风险：`asyncio.wait_for` 取消后 `to_thread` 的线程仍活到 HTTP 客户端 timeout（现 45s→250s），
  挂起连接的线程占用窗口变长；本地单用户工作台，`to_thread` 默认池 min(32, cpu+4)，可接受。
  LLM 调用费用随成功次数上升。顾问面板 refreshAdvisor 仅在开 Tab/应用动作时触发（app.js:863/897，5s 防抖），
  240s 慢响应无请求堆积风险。
- 调用方：前端 abort/文案同步（已列入修复 4）。

**依据不明时的处置**: N/A（各值依据明确：设计注释「用户主动触发，允许完整调用完成」+ 用户指定 240s）。

**⑦.1 方案门**（改代码前填）:
- [x] 覆盖 —— 底账 21 行全部有处置，无「未判定」；「要改」10 行全在修复里。
- [x] 边界 —— wait_for(240) 与客户端(250) 先后次序：250>240 保证 wait_for 先赢、文案为「解读超时」；
  config 缺失时 `_DEFAULT_CONFIG` 已同步 250；config 写成 <240 的用户旧值：钳制后仍生效（尊重配置单源），
  在 README/注释标注要求。并发：残留线程 ≤250s，见影响分析。极值：N/A（纯时长参数）。
- [x] 回退 —— N/A：本条不引入降级/备用路径，只放宽既有硬超时；改回常量即回滚。
- [x] 同步 —— llm_advisor.py:30-31 注释、web_server.py:243 注释、app.js:1025 文案、config.example、本方案文档。
- 已知遗留: 无

---

### 2. 历史恢复（刷新/切任务）后「生成 AI 解读」按钮永久消失

**问题**:
- 复现（playwright 真 Chromium，2026-10-08）：结构化分析后按钮在（`.advice-btn` count=1）；
  **刷新页面并点任务恢复历史后 count=0**——按钮永久消失，与用户描述「AI 解读的按钮也不显示了」吻合。
- 机制：`switchTask`（app.js:217 `clearChat()` + :229 历史重建消息）只重建文本，不补挂按钮。
  另经实测：超时瞬间按钮**不会**消失（变「重试」保留，repro_btn.js t=30s~52s 快照为证），
  消失只发生在历史恢复路径。`/chat` 实时返回才有 `ai_advice` 元数据（web_server.py:1718-1723），
  `/tasks/{id}/messages` 只回 role/content，前端拿不到补挂依据。

**项目定位与设置依据**:
- `addAdviceButton`（app.js:1004）：给结构化分析消息挂「生成 AI 解读」按钮 + 状态区。
  硬编码调用点 :1126（仅 send 实时路径）。
- `ai_advice` 元数据（web_server.py:1718-1723）：`{available, status, analysis_id, params_version}`，
  analysis_id/params_version 由 `set_last_analysis`(:1700) 落 session_state，`get_last_analysis`/`get_params_version` 可取回。
- 契约：`POST /analysis/advice` 以 task_id 为准生成**最新一轮**分析的解读（web_server.py:1292），
  按钮挂在哪条消息上不影响后端语义。

**关联底账**:

| # | 查询 | 范围 | 工具 | 命中 | 落点 | 类别 | 处置 |
|---|------|------|------|------|------|------|------|
| 1 | `addAdviceButton` 挂载点 | src/web_static/*.js | search_files | 2 | :1004 定义、:1126 实时挂载 | 同类实现 | — |
| 2 | `ai_advice` 元数据形状 | web_server.py、tests/ | search_files | 5 | :1718-1723、test_web_server_robustness:196-200 | 配置与常量 | — |
| 3 | `get_last_analysis\|get_params_version\|/messages` 引用 | *.py | search_files | 10 | 见下逐条 | 引用清单 | — |
| 4 | 前端按钮生命周期描述/测试 | *.md、tests/e2e/、tests/*.py | search_files | 5 | 见下逐条 | 文档与测试 | — |

| 落点 | 类别 | 处置 |
|------|------|------|
| app.js:1126 send 实时挂载 | 同类实现 | **不适用**：正常工作（实测按钮在、超时后保留为「重试」） |
| app.js:229 历史恢复不补挂 | 同类实现 | **要改**：恢复后按 meta 补挂到最近一条 assistant 消息 |
| app.js:226-228「应用A/B 按钮不补挂」注释及决定 | 同类实现 | **有意不同**：A/B 按钮依赖 `_pending_ops` 会话态，历史恢复后点击必失败，不补挂是防死按钮的正确决定；AI 解读按钮无此依赖（后端按 task_id 取最新分析），必须补挂 |
| web_server.py:1718-1723 ai_advice meta 形状 | 配置与常量 | **要改**：新增 `GET /tasks/{task_id}/analysis-meta` 镜像此形状（available/status/analysis_id/params_version） |
| web_server.py:89 `get_last_analysis` / :87 `get_params_version` | 引用清单 | **不适用**：复用现有 session_state API，无新依赖 |
| web_server.py:1203 `/tasks/{id}/messages` | 引用清单 | **不适用**：返回形状不动（test_task_api:81/87 锁了形状），meta 走独立新端点 |
| tests/test_task_api.py:81/87 | 引用清单 | **不适用**：messages 契约不变 |
| README.md:72/76（AI 解读按钮行为描述） | 文档与测试 | **不适用**：描述的是召唤时机，不涉按钮生命周期，无失真 |
| tests/e2e/smoke.mjs | 文档与测试 | **不适用**：不覆盖解读按钮；新增 tests/e2e/advice.mjs 专项（见修复） |
| tests/test_web_server_robustness.py:187-257 | 文档与测试 | **不适用**：现有断言不受影响；新端点用例另加 |

盲区：按钮文本搜索不覆盖改名/生成代码（本仓无）；`ops` A/B 按钮、消息分类标签为相邻机制，已在上表区分处置。

**代码环境**:
- 修改点：app.js `switchTask`（历史恢复后补挂）、web_server.py 新端点、tests/e2e/advice.mjs 新增。
- 上游：前端 `switchTask`（app.js:215-230）；后端 session_state `get_last_analysis`。
- 下游：`addAdviceButton` → `POST /analysis/advice`（条目 1 的240s 预算）。
- 测试覆盖：**无**（历史恢复 + 按钮生命周期零覆盖，本次补 e2e）。

**修复**:
1. web_server.py 新增 `GET /tasks/{task_id}/analysis-meta`：`get_last_analysis` 有快照 →
   `{"available": true, "status": "idle", "analysis_id": ..., "params_version": snap.params_version}`；
   无快照 → `{"available": false}`。镜像 /chat 的 ai_advice 形状（web_server.py:1718-1723）。
2. app.js `switchTask`：历史重建后取最后一条 assistant 消息，fetch analysis-meta，`available` 时
   `addAdviceButton(lastAssistantEl, meta, id)`；meta 拉取失败静默跳过（降级=修复前现状，不打扰用户）。
   同步更新 :226-228 注释（区分 A/B 不补挂 vs 解读按钮补挂）。
3. 新增 e2e（先红后绿）`tests/e2e/advice.mjs`：
   - 断言 A：结构化消息 → 按钮出现 → 刷新 + 点任务恢复 → 按钮仍在（修复前红）。
   - 断言 B（前端 abort 预算，条目 1 的前端落点）：route 拦截 `/analysis/advice` 延迟 48s 回包，
     t≈46s 断言仍在 loading（修复前 45s abort 会提前翻「超时」→ 红），回包后断言内容渲染。
4. pytest 新增 `test_tasks_analysis_meta_endpoint`：structured /chat 后 GET meta 与 ai_advice 元数据一致（修复前 404 → 红）。

**影响分析**:
- 现有测试：`/tasks/{id}/messages` 形状不变，test_task_api 不破；新端点无旧断言。
- 正常行为：历史恢复后多一个可用按钮（本次目的）；无分析的旧任务 `available=false` 不显示，不变。
- 新风险：按钮挂到最近一条 assistant 消息上，若用户分析后又闲聊过，按钮位置略偏（语义仍是「对最新分析生成解读」，
  后端契约如此）；meta 请求每任务一次，轻量。stale（参数已变）走现有 stale 路径显示「已过期」，不产生死按钮。
- 调用方：switchTask 自改（已列入修复 2）。

**依据不明时的处置**: 错误实现可改——「按钮消失」不是契约而是历史恢复遗漏（app.js:226-228 注释只论证了 A/B 按钮不该补挂，未涉及解读按钮）；实测确认行为后修复。

**⑦.1 方案门**（改代码前填）:
- [x] 覆盖 —— 底账 10 行全部有处置，无「未判定」；「要改」3 行全在修复里。
- [x] 边界 —— 历史里无 assistant 消息：不挂；无分析快照：`available=false` 不挂；
  meta 请求失败：静默降级为不补挂（=修复前现状）；分析后参数已变：stale 路径已有处理；
  并发/零/空：N/A（纯读端点 + DOM 追加）。
- [x] 回退 —— 补挂失败的降级 = 不显示按钮（修复前行为）；不丢主功能、不吞错误（前端 catch 静默 + 不产生半挂载）。
- [x] 同步 —— app.js:226-228 注释区分两类按钮口径；e2e 文件注释；本方案文档。文档无按钮生命周期描述 → 无需改 README（N/A + 理由：README 只描述召唤时机，不失真）。
- 已知遗留: 按钮挂载消息位置在「分析后又闲聊」场景下偏移（低风险，语义仍正确）——本次不声称修完。

---

## ⑦.2 交付门（2026-10-08 实施后）

**对照记录（先红后绿，红态均为修复前代码实跑）**:
- pytest 红态：`3 failed` —— `test_advice_timeout_budget_is_240s`（`_LLM_ADVICE_TIMEOUT` 不存在）、
  `test_analysis_advice_survives_slow_call`（32s 调用被 30s wait_for 掐死，status=timeout）、
  `test_tasks_analysis_meta_endpoint`（404）。
- e2e 红态：`B: t=46s 前端已提前放弃（旧 45s abort 未修）: {"cls":"ai-advice-status timeout","text":"解读超时，可重试"}`、
  `A: 刷新+任务恢复后 AI 解读按钮消失（历史恢复未补挂）`。
- 修复态全绿（见下）。命中对照口径 1（已有同一断言的失败记录，不撤修复重演）。

**⑦.2**:
- [x] 断言 —— `tests/test_web_server_robustness.py::test_advice_timeout_budget_is_240s`（240s 预算 + 客户端>预算分层不变量）、`::test_analysis_advice_survives_slow_call`（32s 慢调用存活）、`::test_tasks_analysis_meta_endpoint`（meta 契约 + 无分析 available=false）；`tests/e2e/advice.mjs` 断言 A（历史恢复补挂）、断言 B（48s 延迟回包不被 45s abort 掐断）。全部锁修复后意图。
- [x] 对照 —— 见上红态记录；撤掉修复目标断言即红（实跑记录），恢复后绿。
- [x] 门禁 —— 收工态一次跑齐：`make lint`（0 errors，4 个 warning 均为原有代码）、`make smoke`（smoke_ok 0.3.0）、`make compile`、`make test`（**518 passed**）、`make e2e`（smoke.mjs + advice.mjs 全过）。
- [x] 现场 —— `git diff` 无新增 TODO/FIXME/注释掉的代码/调试残留（grep 实查）。
- [x] 同步 —— ⑦.1 同步项逐项落地：llm_advisor.py:30-34 注释（分层口径）、web_server.py:241-247 注释、app.js:1025 文案（「最长约 4 分钟」）、app.js:226-240 注释（A/B 不补挂 vs 解读按钮补挂的口径区分）、config/agent_llm_config.json.example、本方案文档。
- [x] 底账 —— ③两表「要改」行全部落地（web_server 常量+2 调用点、llm_advisor 上限、config×3、app.js abort+文案、app.js 历史恢复补挂、meta 端点、测试×2）；「有意不同」行仍成立（闲聊 8s、/chat 60s、.bak 不动、A/B 不补挂）；行数与③一致。
