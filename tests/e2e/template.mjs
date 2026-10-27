// M-06 模板预填 + 改参切结构化 e2e（2026-10）——P-04/P-06 验收。
//
// 计划验收（M-06 行）：「网络面板只见 PUT；选行业后表单预填」。
// 四步独立 try/catch：单步失败不吞后续步骤的红位（红位核对用）。
// 预期值不硬编码——从 /form-schema 的 templates 推导（schema 驱动契约，
// 同 form.mjs 口径：DOM 必须镜像 schema，谁脱钩谁红）。
// 卫生断言与 smoke.mjs 同口径：零 console error / 零未捕获 / 零 /client-log。
//
// 运行：make e2e（或 node tests/e2e/template.mjs）
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", "..");
const PORT = 8098;
const BASE = `http://127.0.0.1:${PORT}`;

function log(...a) { console.log("[e2e-template]", ...a); }
// FAIL: 后接步骤标签——red_manifest --log 按 "] FAIL:" 提取行、--expect-steps 按子串匹配
function fail(step, msg) { console.error("[e2e-template] FAIL:", step, msg); process.exitCode = 1; }

async function waitHealthy(timeoutMs = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try { const r = await fetch(`${BASE}/health`); if (r.ok) return; } catch { /* 服务还没起来 */ }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("server did not become healthy");
}

// 与 formInputValue 同口径：0~1 比率显示成百分数（0.4 → '40'），其余原样
function expectedDisplay(spec, v) {
  if (spec.unit === "0~1" && typeof v === "number") return String(Math.round(v * 100 * 1e4) / 1e4);
  return String(v);
}

const storeDir = mkdtempSync(path.join(tmpdir(), "shangzhu-e2e-tpl-"));
const server = spawn(
  path.join(ROOT, ".venv", "bin", "python3"),
  ["-c", `import uvicorn; from web_server import app; uvicorn.run(app, host="127.0.0.1", port=${PORT}, log_level="warning")`],
  {
    cwd: ROOT,
    env: {
      ...process.env,
      LOCAL_STORE_PATH: storeDir,
      PGDATABASE_URL: "postgresql://nobody@127.0.0.1:1/shangzhu_test", // 必败→降级 JSON，隔离
    },
    stdio: "ignore",
  },
);

let browser;
try {
  await waitHealthy();
  // 端口冲突守卫（M-07 事故：孤儿 uvicorn 占端口 → waitHealthy 静默打到旧代码服务器 = 假红）
  await new Promise((r) => setTimeout(r, 600));
  if (server.exitCode !== null) {
    fail("启动", `端口 ${PORT} 被旧进程占用，本测试自己的服务没起来（先 kill 旧 uvicorn）`);
    throw new Error(`port ${PORT} occupied by stale server`);
  }
  log("server healthy, launching chromium ...");

  const schema = await (await fetch(`${BASE}/form-schema`)).json();
  const fieldNames = schema.input_fields.map((f) => f.name);
  const specByName = Object.fromEntries(schema.input_fields.map((f) => [f.name, f]));
  const tplKeys = Object.keys(schema.templates || {});
  if (!tplKeys.length) { fail("预填", "schema.templates 为空——预填无数据源"); }
  const IND = tplKeys[0];
  const hyp = (schema.templates[IND] && schema.templates[IND].hypotheses) || {};
  const bench = (schema.templates[IND] && schema.templates[IND].benchmark) || {};
  const hypFields = Object.keys(hyp).filter((k) => fieldNames.includes(k));
  log(`schema: fields=${fieldNames.length} 行业=${tplKeys.length} 预填字段=${hypFields.length}`);

  browser = await chromium.launch();
  const page = await browser.newPage();
  const consoleErrors = [], pageErrors = [], clientLogPosts = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => pageErrors.push(String(e)));
  page.on("request", (r) => { if (r.url().endsWith("/client-log")) clientLogPosts.push(r.url()); });

  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.click("#new-task");
  await page.waitForTimeout(1200);
  await page.waitForSelector("#params-list input[data-field]", { timeout: 5000 });

  // ── 步骤1 选行业预填：空字段填入模板值 + [默认] 标 + benchmark 参考列 ──
  try {
    await page.waitForSelector("#pf-industry", { timeout: 3000 });
    await page.selectOption("#pf-industry", IND);
    await page.waitForTimeout(300);
    let bad = [];
    for (const k of hypFields) {
      const got = await page.$eval(`#params-list input[data-field='${k}']`, (e) => e.value);
      const want = expectedDisplay(specByName[k], hyp[k]);
      if (got !== want) bad.push(`${k}: got=${got} want=${want}`);
    }
    if (hypFields.length < 3) bad.push(`预填字段数 ${hypFields.length} < 3——预填覆盖面不足`);
    if (bad.length) fail("预填", bad.join("; "));
    const markers = await page.$$eval("#params-list .psrc-default", (els) => els.length);
    if (markers < Math.min(hypFields.length, 3)) fail("预填", `[默认] 标 ${markers} 个 < 预填字段数`);
    const benchText = await page.textContent("#params-list .pf-bench").catch(() => "");
    const benchKeys = Object.keys(bench);
    const benchMissing = benchKeys.filter((k) => !benchText.includes(String(bench[k])));
    if (!benchKeys.length || benchMissing.length) fail("预填", `benchmark 参考列缺: ${benchMissing.join(",") || "整块缺失"}`);
    if (!process.exitCode) log(`步骤1 预填 ✓: ${hypFields.length} 字段 + [默认]标 + benchmark ${benchKeys.length} 条`);
  } catch (e) { fail("预填", String(e && e.message ? e.message : e)); }

  // ── 步骤2 预填保存闭环：保存 → PUT 200 → 落库 ──
  try {
    const putPromise = page.waitForResponse(
      (r) => r.request().method() === "PUT" && /\/tasks\/[^/]+\/params$/.test(r.url()), { timeout: 8000 });
    await page.click("#params-list .pf-save");
    const putResp = await putPromise;
    if (putResp.status() !== 200) fail("保存", `PUT 状态 ${putResp.status()} != 200`);
    await page.waitForTimeout(400);
    const tasks = await (await fetch(`${BASE}/tasks`)).json();
    const cur = tasks[0];
    const miss = hypFields.filter((k) => !cur || cur.params?.[k] === undefined || cur.params?.[k] === null);
    if (miss.length) fail("保存", `模板值未落库: ${miss.join(",")}`);
    else log(`步骤2 保存 ✓: ${hypFields.length} 模板值落库`);
  } catch (e) { fail("保存", String(e && e.message ? e.message : e)); }

  // ── 步骤3 重置为模板默认：改乱 → 按节重置 → 恢复模板值 ──
  try {
    const k0 = hypFields[0];
    const sec = `#params-list details:has(input[data-field='${k0}'])`;
    await page.fill(`#params-list input[data-field='${k0}']`, "999");
    await page.click(`${sec} .pf-reset`);
    await page.waitForTimeout(200);
    const got = await page.$eval(`#params-list input[data-field='${k0}']`, (e) => e.value);
    const want = expectedDisplay(specByName[k0], hyp[k0]);
    if (got !== want) fail("重置", `重置后 ${k0}=${got} != 模板默认 ${want}`);
    else log(`步骤3 重置 ✓: ${k0} 恢复 ${want}`);
  } catch (e) { fail("重置", String(e && e.message ? e.message : e)); }

  // ── 步骤4 改参只见 PUT（M-08：旧改参区已删，改参唯一路径 = 右侧表单）──
  try {
    // 确认层造参：NL → 确认条 → 确认开算（PUT price_per_unit=15 进引擎）
    await page.fill("#input", "客单价15元");
    await page.click("#send");
    await page.waitForSelector("#params-list .pf-confirm", { timeout: 8000 });
    await page.click("#params-list .pf-confirm-ok");
    await page.waitForTimeout(600);
    // 旧改参区必须不存在（M-08 计划性删除，留 DOM 不留 JS = 死按钮）
    if (await page.$("#params-controls")) fail("只见PUT", "旧改参区 #params-controls 仍在（M-08 应删）");
    // 表单改值 → 保存 → 网络窗口只见 PUT、零 /chat
    await page.fill("#params-list input[data-field='price_per_unit']", "18");
    const window = [];
    const onReq = (r) => window.push(`${r.method()} ${r.url()}`);
    page.on("request", onReq);
    const putPromise = page.waitForResponse(
      (r) => r.request().method() === "PUT" && /\/tasks\/[^/]+\/params$/.test(r.url()), { timeout: 8000 });
    await page.click("#params-list .pf-save");
    const putResp = await putPromise;
    if (putResp.status() !== 200) fail("只见PUT", `PUT 状态 ${putResp.status()} != 200`);
    await page.waitForTimeout(300);
    page.off("request", onReq);
    const chats = window.filter((s) => s.includes("/chat"));
    if (chats.length) fail("只见PUT", `改参窗口出现 ${chats.length} 个 /chat 请求`);
    const tasks = await (await fetch(`${BASE}/tasks`)).json();
    if (tasks[0]?.params?.price_per_unit !== 18) fail("只见PUT", `保存后 price_per_unit=${tasks[0]?.params?.price_per_unit} != 18`);
    if (!process.exitCode) log("步骤4 改参只见 PUT ✓: 旧改参区已删，表单路径零 /chat，price=18 落库");
  } catch (e) { fail("只见PUT", String(e && e.message ? e.message : e)); }

  // ── 卫生断言 ──
  if (consoleErrors.length) fail("卫生", `console errors: ${JSON.stringify(consoleErrors)}`);
  if (pageErrors.length) fail("卫生", `uncaught page errors: ${JSON.stringify(pageErrors)}`);
  if (clientLogPosts.length) fail("卫生", `前端错误上报被触发: ${clientLogPosts.length} 次`);

  if (process.exitCode !== 1) log("PASS: 预填+保存+重置+只见PUT, 卫生全清");
} catch (e) {
  fail("启动", String(e && e.stack ? e.stack : e));
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill("SIGTERM");
}