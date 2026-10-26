// M-07 NL 确认层 e2e（2026-10）——「不确认不进引擎；跳过开关生效」验收。
//
// 四步独立 try/catch：单步失败不吞后续步骤的红位（红位核对用）。
// 产品默认：确认层开（前端默认发送 nl_confirm=true）——本文件全程走默认路径，
// 跳过开关只在第 4 步经真实 UI（表单底栏复选框）打开。
// 卫生断言与 smoke.mjs 同口径：零 console error / 零未捕获 / 零 /client-log。
//
// 运行：make e2e（或 node tests/e2e/confirm.mjs）
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", "..");
const PORT = 8099;
const BASE = `http://127.0.0.1:${PORT}`;

function log(...a) { console.log("[e2e-confirm]", ...a); }
function fail(step, msg) { console.error("[e2e-confirm] FAIL:", step, msg); process.exitCode = 1; }

async function waitHealthy(timeoutMs = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try { const r = await fetch(`${BASE}/health`); if (r.ok) return; } catch { /* 服务还没起来 */ }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("server did not become healthy");
}

const storeDir = mkdtempSync(path.join(tmpdir(), "shangzhu-e2e-confirm-"));
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
  // 端口冲突守卫（2026-10 事故：红阶段崩溃致 uvicorn 孤儿进程占住端口，
  // 新服务绑定失败被 stdio ignore 吞掉，测试静默打到旧代码服务器上——假红）。
  await new Promise((r) => setTimeout(r, 600));
  if (server.exitCode !== null) {
    fail("启动", `端口 ${PORT} 被旧进程占用，本测试自己的服务没起来（先 kill 旧 uvicorn）`);
    throw new Error(`port ${PORT} occupied by stale server`);
  }
  log("server healthy, launching chromium ...");

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

  const snapshotParams = async () => {
    const tasks = await (await fetch(`${BASE}/tasks`)).json();
    return tasks[0]?.params || {};
  };

  // ── 步骤1 确认层拦截：NL 抽取 → 表单预填 [待确认]，引擎快照无该值 ──
  try {
    await page.fill("#input", "客单价15元");
    await page.click("#send");
    await page.waitForSelector("#params-list .pf-confirm", { timeout: 8000 });
    const got = await page.$eval("#params-list input[data-field='price_per_unit']", (e) => e.value);
    if (got !== "15") fail("确认层", `表单预填 price_per_unit=${got} != 15`);
    const markers = await page.$$eval("#params-list .psrc-pending", (els) => els.length);
    if (markers < 1) fail("确认层", "[待确认] 来源标缺失");
    const snap = await snapshotParams();
    if (snap.price_per_unit !== undefined) fail("确认层", `未确认值竟进引擎快照: ${JSON.stringify(snap)}`);
    if (!process.exitCode) log("步骤1 确认层 ✓: 预填 15 + [待确认] + 引擎未污染");
  } catch (e) { fail("确认层", String(e && e.message ? e.message : e)); }

  // ── 步骤2 确认开算：点「确认开算」→ PUT 落库 → 确认条消失 ──
  try {
    const okBtn = await page.$("#params-list .pf-confirm-ok");
    if (!okBtn) { fail("确认开算", "确认条不存在（前置步骤失败或确认层未接线）"); }
    else {
      const putPromise = page.waitForResponse(
        (r) => r.request().method() === "PUT" && /\/tasks\/[^/]+\/params$/.test(r.url()), { timeout: 8000 });
      await okBtn.click();
      const putResp = await putPromise;
      if (putResp.status() !== 200) fail("确认开算", `PUT 状态 ${putResp.status()} != 200`);
      await page.waitForTimeout(400);
      const snap = await snapshotParams();
      if (snap.price_per_unit !== 15) fail("确认开算", `确认后未落库: ${JSON.stringify(snap)}`);
      const barGone = await page.$$("#params-list .pf-confirm");
      if (barGone.length) fail("确认开算", "确认后确认条未消失");
      if (!process.exitCode) log("步骤2 确认开算 ✓: PUT 200 + price_per_unit=15 落库");
    }
  } catch (e) { fail("确认开算", String(e && e.message ? e.message : e)); }

  // ── 步骤3 忽略：新 NL → 确认条 → 点「忽略」→ 引擎快照无该值、表单回滚 ──
  try {
    await page.fill("#input", "月租金3000元");
    await page.click("#send");
    await page.waitForSelector("#params-list .pf-confirm", { timeout: 8000 });
    const before = await page.$eval("#params-list input[data-field='monthly_rent']", (e) => e.value);
    if (before !== "3000") fail("忽略", `预填 monthly_rent=${before} != 3000`);
    await page.click("#params-list .pf-confirm-ignore");
    await page.waitForTimeout(300);
    const after = await page.$eval("#params-list input[data-field='monthly_rent']", (e) => e.value).catch(() => "");
    const snap = await snapshotParams();
    if (after !== "") fail("忽略", `忽略后表单未回滚: monthly_rent=${after}`);
    if (snap.monthly_rent !== undefined) fail("忽略", `忽略后引擎竟有值: ${JSON.stringify(snap)}`);
    if (!process.exitCode) log("步骤3 忽略 ✓: 表单回滚 + 引擎未污染");
  } catch (e) { fail("忽略", String(e && e.message ? e.message : e)); }

  // ── 步骤4 跳过开关：勾选「NL 免确认直接生效」→ NL 直接进引擎 ──
  try {
    await page.check("#params-list #pf-skip-confirm");
    await page.fill("#input", "员工3人");
    await page.click("#send");
    await page.waitForTimeout(2500);
    const barVisible = await page.$$("#params-list .pf-confirm");
    if (barVisible.length) fail("跳过开关", "跳过后仍出现确认条");
    const snap = await snapshotParams();
    if (snap.employee_count !== 3) fail("跳过开关", `跳过后未直接进引擎: ${JSON.stringify(snap)}`);
    if (!process.exitCode) log("步骤4 跳过开关 ✓: employee_count=3 直接落库，零确认条");
  } catch (e) { fail("跳过开关", String(e && e.message ? e.message : e)); }

  // ── 卫生断言 ──
  if (consoleErrors.length) fail("卫生", `console errors: ${JSON.stringify(consoleErrors)}`);
  if (pageErrors.length) fail("卫生", `uncaught page errors: ${JSON.stringify(pageErrors)}`);
  if (clientLogPosts.length) fail("卫生", `前端错误上报被触发: ${clientLogPosts.length} 次`);

  if (process.exitCode !== 1) log("PASS: 确认层拦截+确认开算+忽略+跳过开关, 卫生全清");
} catch (e) {
  fail("启动", String(e && e.stack ? e.stack : e));
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill("SIGTERM");
}