# 修复方案：连通性探测超时 5s→30s + base_url 双拼路径归一（2026-10-08）

> 依据 code-fix-completeness-audit v2.0 七步产出。实施前过 ⑦.1，实施后过 ⑦.2（结果见文末）。
> 症状（用户原话）：大模型设置「已保存，但连通性测试未通过，探测超时」。

---

### 1. 连通性探测超时预算 5s → 30s（+ 摘出事件循环阻塞）

**问题**:
- 复现（curl 实打运行中服务 127.0.0.1:8081，2026-10-08）：POST `/settings/llm/test` 连测 3 次，
  **3/3 返回 `{"ok":false,"error":"探测超时（>5s）"}`，实际耗时 9.2/10.5/9.2s**——请求本来
  能在 9~10s 完成，被 5s 预算掐死。
- 离线量化（项目 .venv，requests 复刻探测请求，max_tokens=1）：9 次全部 HTTP 200，
  延迟分布 2.3/2.8/3.7/6.6/6.8/7.2/8.4/8.6/2.8s，**5/9 次 >5s**；裸 TLS 握手另有 2 次
  12~13s 超时。本机直连 openrouter.ai（Cloudflare）延迟抖动大，5s 预算必然间歇性失败。
- 网络层排除：DNS 多次取样 0.01s 正常（104.18.x Cloudflare）；无系统代理、无 proxy env
  （NO_PROXY 旁路 hack 非本案因素）；key 与模型名有效（200 响应 `xiaomi/mimo-v2.5-pro`，provider GMICloud）。
- 连带缺陷：`test_llm_settings` 是 `async def`，内部**同步**调 `test_llm_config`
  （requests.post 阻塞调用）——预算提到 30s 后会把整个事件循环卡 30s，必须先摘到线程池。

**项目定位与设置依据**:
- `test_llm_config`（src/llm_advisor.py:745-802）：保存后的连通性探测，同步 requests.post，
  `timeout=5` 硬编码（:788），超时文案硬编码「探测超时（>5s）」（:796）。设置依据：docstring
  自述「超时 5s，避免拖慢保存体验」（:750）——当年按快网络定的，与本机到 openrouter 的
  实际延迟不匹配。硬编码。
- `test_llm_settings`（web_server.py:1149-1183）：`async def` + 同步探测调用（:1177）。
- 前端 `testLlmConfig`（app.js:71-87）：fetch 无超时/无 abort，toast 文案
  「已保存，但连通性测试未通过：」+ 后端 error（:83）——即用户看到的原文。
- 依据不明时的处置：N/A（各值来源均可查，注释/审计文档在案）。

**关联底账**:

| # | 查询 | 范围 | 工具 | 命中 | 落点 | 类别 | 处置 |
|---|------|------|------|------|------|------|------|
| 1 | `timeout=5` | src/ + config/ + web_server.py | search_files | 3 | llm_advisor.py:788（探测）、llm_advisor.py:46（keychain subprocess） | 同类实现 | :788 **要改**；:46 有意不同（本地 security CLI 5s 充足） |
| 2 | `探测超时` | src/、tests/、app.js | search_files | 2 | llm_advisor.py:796 文案、tests/test_llm_settings.py:160（断言含「超时」） | 同类实现 | :796 **要改**（动态化）；tests 锁「超时」字样——保留字样，兼容 |
| 3 | `test_llm_config` 引用 | *.py | search_files | 3 | 定义 :745、web_server.py:114 调用 :1177、本文件 docstring | 引用清单 | 调用点 web_server:1177 **要改**（to_thread）；其余随函数内改 |
| 4 | `连通性|探测` | docs/、reports/、README、AGENT.md | search_files | 21 | except-audit-20261003.md:50（B 项：探测异常无服务端日志，建议补 logger.warning）；reports/engineering_integrity_audit（历史结论） | 文档与测试 | except-audit B 项由条目 3 落地；其余历史记录不动 |
| 5 | tests 对探测的锁定 | tests/test_llm_settings.py | read_file | 8 用例 | 全部 monkeypatch requests.post，不锁 timeout 数值/URL | 文档与测试 | 不适用（不挡路）；本次另加预算/URL 断言 |

盲区：`scripts/` 无探测引用；生成代码/其他语言不适用（Python+JS）；keychain timeout=5 语义不同已区分。

**代码环境**:
- 修改点：llm_advisor.py 常量区+探测函数；web_server.py:1177 调用方式。
- 上游：前端保存 → `testLlmConfig(body)` → POST `/settings/llm/test`。
- 下游：requests.post → openrouter.ai（Cloudflare 直连）。
- 测试覆盖：test_llm_settings.py 8 用例（mock 层），真实超时预算无覆盖（本次补）。

**修复**:
1. llm_advisor.py 新增模块常量 `_PROBE_TIMEOUT_S = 30.0`（注释：本机直连 openrouter 实测
   max_tokens=1 全程 2.3~8.6s、TLS 握手最长 13s，5s 必挂；30s ≈ 3× 最坏观测；
   分层口径：闲聊 8s < 探测 30s < 解读 240s < HTTP 客户端 250s）。
2. :788 `timeout=5` → `timeout=_PROBE_TIMEOUT_S`；:796 文案 → `f"探测超时（>{int(_PROBE_TIMEOUT_S)}s）"`；
   :750 docstring 同步。
3. web_server.py:1177 → `result = await asyncio.to_thread(test_llm_config, model, base_url, api_key)`
   （asyncio 已 import :44；探测最长 30s 不再阻塞事件循环）。
4. 新增测试（先红后绿，tests/test_llm_settings.py）：
   - `test_probe_timeout_budget_is_30s`：断言 `_PROBE_TIMEOUT_S == 30.0` 且文案含预算数（分层不变量）。
   - 前端不动（fetch 无 abort，后端预算即 UX 上限；toast 延迟 ≤30s 可接受，写入注释）。

**影响分析**:
- 现有测试：不打破（探测用例全 mock；`test_test_endpoint_timeout` 锁「超时」字样——新文案仍含）。
- 正常行为：快网络（<5s）行为完全不变；5~30s 的慢网络从「必挂」变为「能通过」（本次目的）。
- 新风险：探测占用 worker 线程最长 30s（本地单用户，`to_thread` 默认池够用）；
  保存后 toast 最长延迟 30s（原 5s）；无并发探测堆积（保存弹窗单实例）。
- 调用方：web_server.py:1177 已列入修复 3；前端无改动。

**依据不明时的处置**: N/A（5s 的原始依据在 docstring，改为 30s 的依据是本机实测延迟分布）。

---

### 2. base_url 双拼路径：探测与主链路都会拼出 `/chat/completions/chat/completions`

**问题**:
- config 单源里 base_url = `https://openrouter.ai/api/v1/chat/completions`（完整端点形态）。
- 探测侧（llm_advisor.py:776）：`base_url.rstrip("/") + "/chat/completions"` → **双拼**。
- 主链路侧：`_get_llm` 把原样 base_url 传给 ChatOpenAI（:401）；openai SDK 2.24.0 的
  URL 合并是「base 路径直拼相对路径」（site-packages/openai/_base_client.py:468-474）→ **主链路同样双拼**。
- 实证：双拼 URL 在 OpenRouter 上仍 200（网关容错），但这是侥幸——换严格网关
  （如 DeepSeek 官方 API）即 404；且项目自己的默认值就是 SDK 形态
  （settings.py:28 `https://api.deepseek.com/v1`、example 同），完整端点形态是用户输入习惯，
  项目对两种形态均无归一化。

**项目定位与设置依据**:
- `get_base_url`（llm_advisor.py:229-237）：配置单源读取，原样返回。调用方 3 处：
  `_get_llm`:375（主链路）、web_server.py:140 `ENDPOINT`（import 期快照，定义后无下游使用）、
  web_server.py:1048（状态接口动态展示）。
- `save_llm_config`（config/settings.py:197，真正实现）：`inner["base_url"] = base_url.strip()`（:219），
  不归一。llm_advisor.py:631 同名函数是 F6 委托包装（委托 settings，兜底本地实现），**有意不同**。
- `normalize` 放 config/settings.py：settings 是底层（无反向依赖），llm_advisor 顶层导入它无环。

**关联底账**:

| # | 查询 | 范围 | 工具 | 命中 | 落点 | 类别 | 处置 |
|---|------|------|------|------|------|------|------|
| 1 | `chat/completions` | src/llm_advisor.py | search_files | 2 | :776（探测拼 URL）；主链路经 SDK 拼接（源码 :468-474） | 同类实现 | **要改**（两处归一） |
| 2 | `chat/completions` | config/*.json | search_files | 2 | agent_llm_config.json / .bak（完整端点形态存量） | 配置与常量 | **要改**（保存时归一；存量文件靠读取时归一兜底，不做数据迁移） |
| 3 | `get_base_url()` 引用 | src/ + web_server.py | search_files | 3 | llm_advisor:375 主链路、web_server:140 ENDPOINT（无下游）、:1048 状态展示 | 引用清单 | **要改**（get_base_url 内归一，三处受益）；ENDPOINT 不适用（归一随函数免费生效） |
| 4 | `save_llm_config` 定义 | config/settings.py、llm_advisor.py | search_files | 2 | settings:197 真实现、llm_advisor:631 F6 委托包装 | 同类实现 | settings **要改**（归一落点）；llm_advisor:631 有意不同（委托+兜底，归一在 settings 层生效） |
| 5 | example/默认值 base_url 形态 | agent_llm_config.json.example、settings.py:28 | search_files | — | 均为 SDK 形态（无 /chat/completions） | 配置与常量 | 不适用（归一后与项目自身约定一致） |
| 6 | tests 对 base_url 形态的锁定 | tests/ | search_files | 0 | 无 | 文档与测试 | 不适用（无既有锁定）；本次新增归一断言 |

盲区：`.venv` 第三方源码（已按需查证 SDK 拼接逻辑）；`scripts/` 无 base_url 拼接；前端只透传不改写。

**代码环境**:
- 修改点：config/settings.py（helper + 保存归一）、llm_advisor.py（get_base_url、探测 URL）。
- 上游：设置弹窗提交的 base_url（用户手输）。
- 下游：探测 requests.post；ChatOpenAI → openai SDK → 网关。
- 测试覆盖：无 base_url 形态锁定（本次补）。

**修复**:
1. config/settings.py 新增 `normalize_base_url(base_url) -> str`：rstrip("/") + 剥离尾部
   `/chat/completions`（while 循环，容忍病态重复后缀；空串返回空串）。
2. settings.py:219 保存时 `inner["base_url"] = normalize_base_url(base_url)`（存量文件不做迁移，
   读取/探测侧归一兜底；下次保存自然归一）。
3. llm_advisor.py：顶层 `from config.settings import normalize_base_url`；
   `get_base_url` 返回归一值（fallback 分支同理）；探测 :776 改为
   `normalize_base_url(base_url) + "/chat/completions"`（SDK 形态输入同样正确）。
4. 新增测试（先红后绿，tests/test_llm_settings.py）：
   - `test_normalize_base_url_variants`：完整端点→v1 根；SDK 形态不变；尾斜杠；病态双后缀。
   - `test_probe_url_single_completion_suffix`：mock post 捕获 URL，完整端点输入 →
     请求 URL 恰好一个 `/chat/completions`（修复前双拼 → 红）。
   - `test_probe_url_appends_for_sdk_form`：`https://api.deepseek.com/v1` → 追加一次（防过剥）。
   - `test_save_normalizes_base_url`：保存完整端点形态 → GET 视图为 v1 根（先存原值，finally 还原）。
   - `test_get_llm_base_url_normalized`：mock `_load_llm_config` 返回完整端点形态 →
     `_get_llm().root_client.base_url` 为 v1 根（主链路归一）。

**影响分析**:
- 现有测试：不打破（无 base_url 形态断言；test_save_* 用例 base_url 来自现有配置，
  归一后值等价语义不变——现有配置是完整端点形态，保存用例回写会变成 v1 根，
  `test_save_model_updates_health` 断言只看 status_code，不比对值 → 安全）。
- 正常行为：OpenRouter 上探测与主链路从「双拼侥幸通」变为「单路径正确通」
  （实测两种 URL 形态均 200，行为无回退）；严格网关从「会 404」变为「正确」。
- 新风险：存量 config 文件仍存完整端点形态（读取时归一兜底，无功能差异）；
  若有人依赖「配置文件里存完整端点」的展示习惯，GET 视图会显示归一后形态——
  与项目自身占位符/默认值口径一致（均为 SDK 形态）。
- 调用方：get_base_url 三个调用点全部受益，无需各自改动。

**依据不明时的处置**: 错误实现可改——双拼不是契约（无测试锁定、无文档主张完整端点形态必须保留；
SDK 源码拼接行为 + 双端点实测 + 项目默认形态三证齐全）。

---

### 3. 探测异常分支无服务端日志（except-audit B 项落地）

**问题**: docs/except-audit-20261003.md:50：「:798 探测异常返回结构化 error，服务端无日志 → 补 logger.warning」。
当前 llm_advisor.py:794-801 Timeout/ConnectionError/Exception 三分支均不落日志，
前端 toast 只见「探测超时」无耗时/无上下文，排查全靠盲猜（本次调查就被迫离线复刻）。

**项目定位与设置依据**: `test_llm_config` 异常分支（:794-801）；审计文档既有建议条目。
**关联底账**:

| # | 查询 | 范围 | 工具 | 命中 | 落点 | 类别 | 处置 |
|---|------|------|------|------|------|------|------|
| 1 | except-audit 探测日志建议 | docs/except-audit-20261003.md | search_files | 1 | :50 | 文档与测试 | **要改**（落地该建议） |
| 2 | 探测分支现有日志 | src/llm_advisor.py:756-802 | read_file | 0 | 三分支均无日志 | 同类实现 | **要改**（补 warning，不透传 key/响应体） |

盲区：无（该函数仅此三异常分支）。

**代码环境**:
- 修改点：llm_advisor.py:794-801。
- 上游/下游：同条目 1。测试覆盖：无（本次顺带断言日志存在性——可选，不强制）。

**修复**: 三分支各补 `logger.warning("连通性探测失败: %s, url=%s, latency=%dms", ...)`；
日志不含 key、不含响应体（S6 口径；URL 与耗时可记）。

**影响分析**:
- 现有测试：不打破。正常行为：不变（只加日志）。新风险：无。
- 调用方：无。
**依据不明时的处置**: N/A（审计文档既有建议，非新主张）。

---

**⑦.1 方案门**（改代码前填）:
- [x] 覆盖 —— 三条目底账共 13 行全部有处置，无「未判定」；「要改」行全部进修复。
- [x] 边界 —— base_url 尾斜杠/SDK 形态/病态重复后缀/空串（helper while 剥离 + rstrip）；
  无 scheme 输入：现有 `_validate_llm_url` 拒绝路径不变（归一不改 host/scheme）；
  探测 30s 极值：to_thread 不阻塞事件循环；并发探测：无堆积场景；
  NO_PROXY env 突变：既有设计保留（本机无代理，不影响）。
- [x] 回退 —— N/A：不引入降级/备用路径；改回常量/去掉归一即回滚。
- [x] 同步 —— llm_advisor.py:750 docstring 与 :796 文案、新增方案文档、新增测试；
  except-audit-20261003.md 为历史审计记录不改（其建议由条目 3 实施）；README/AGENT.md 无探测描述 → N/A。
- 已知遗留: 有 —— (a) web_server.py:140 `ENDPOINT` import 期快照不随保存刷新——既有设计，
  本次不改，低；(b) ~~fangan1 有同款探测代码（timeout=5 + 双拼），本次不动~~
  **[缺口不实，2026-10-08 复核删除]**：fangan1 已于 2026-09-19 自修——有
  `tests/test_llm_endpoint_normalize.py` 守护（SDK 双拼 httpx hook 实证 + normalize_base_url
  剥离行为 + 测试/运行两路径共用 _build_llm_client），config 已是归一形态
  `https://openrouter.ai/api/v1`，用户实测连通正常。当时的错误来自取证盲区：
  只 grep 了 `timeout=5` 与 `chat/completions` 命中数，未搜 `normalize_base_url`。

---

## ⑦.2 交付门（2026-10-08 实施后）

**对照记录（先红后绿）**:
- pytest 红态（修复前实跑，TestProbeHardening）：`5 failed, 1 passed`——
  `test_probe_timeout_budget_is_30s`（_PROBE_TIMEOUT_S 不存在）、
  `test_normalize_base_url_variants`（normalize_base_url 不存在）、
  `test_probe_url_single_completion_suffix`（mock 捕获到双拼 URL）、
  `test_save_normalizes_base_url`（保存后仍是完整端点形态）、
  `test_get_llm_base_url_normalized`（root_client.base_url 双拼）；
  `test_probe_url_appends_for_sdk_form` 修复前即绿（防归一过度剥离的守卫用例）。
- 实弹 A/B（同网络窗口，对运行服务 127.0.0.1:8081，真实 key）：
  修复前 3/3 `{"ok":false,"error":"探测超时（>5s）"}`，耗时 9.2/10.5/9.2s；
  修复后（重启加载新代码）3/3 `{"ok":true,"status_code":200}`，latency 5.0/5.4/6.0s
  ——三次延迟同样 >5s，旧代码仍会全挂，新代码全过。命中对照口径 1
  （已有失败记录 + 修复态通过，不撤修复重演）。
- `/health` 佐证：endpoint 显示归一形态 `https://openrouter.ai/api/v1`（web_server.py:1048 动态取 get_base_url）。

**⑦.2**:
- [x] 断言 —— tests/test_llm_settings.py::TestProbeHardening 6 用例锁修复后意图：
  预算常量 30s、归一各形态（完整端点/尾斜杠/病态双后缀/空串）、探测 URL 恰好单拼、
  SDK 形态仍追加、保存归一落盘、主链路 client base_url 归一。
- [x] 对照 —— 见上红态记录；既有 `test_test_endpoint_timeout`（锁「超时」文案）修复后仍绿（19 passed 含之）。
- [x] 门禁 —— 收工态一次跑齐：`make lint`（0 errors，4 warnings 均原有 app.js 代码）、
  `make compile`、`make smoke`（smoke_ok 0.3.0 mimo-v2.5-pro）、`make test`（**524 passed**
  = 前次交付 518 + 新增 6，数目吻合）、`make e2e`（smoke.mjs + advice.mjs 全 PASS）。
- [x] 现场 —— 三改动文件 grep `TODO|FIXME|XXX|print(` 零命中。
- [x] 同步 —— llm_advisor.py docstring（探测预算口径）、:796 动态文案、常量区注释、
  get_base_url/归一注释、web_server.py:1177 to_thread 注释、本方案文档、新增测试；
  except-audit-20261003.md 为历史审计记录不改，其 B 项（探测日志）由条目 3 实施落地。
- [x] 底账 —— ③三表「要改」行全部落地（llm_advisor:788/:796/:776/get_base_url、
  settings.py save:219+helper、web_server:1177、三 except 日志）；
  「有意不同」仍成立（keychain timeout=5 本地 CLI、llm_advisor:631 F6 委托包装、
  example/.bak 不适用、ENDPOINT import 期快照遗留）；行数与③一致。
- 已知遗留（同⑦.1）：fangan1（另一项目，8080）同款探测代码未修（低）；ENDPOINT 快照（低）。
