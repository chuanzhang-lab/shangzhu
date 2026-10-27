// M-05 表单 e2e（2026-10）——schema 驱动渲染契约 + 缺参可填 + PUT 闭环。
//
// 计划验收（M-05 行）：「字段数 = INPUT_SPECS 输入字段数；缺参字段可填」。
// 关键设计：字段数不硬编码——测试先拉 /form-schema，断言 DOM 输入框数 ==
// schema.input_fields 数（DOM 必须镜像 schema，谁脱钩谁红）。
// 卫生断言与 smoke.mjs 同口径：零 console error / 零未捕获 / 零 /client-log。
//
// 运行：make e2e  （或 node tests/e2e/form.mjs）
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..", "..");
const PORT = 8097;
const BASE = `http://127.0.0.1:${PORT}`;

function log(...a) { console.log("[e2e-form]", ...a); }
function fail(msg) { console.error("[e2e-form] FAIL:", msg); process.exitCode = 1; }

async function waitHealthy(timeoutMs = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`${BASE}/health`);
      if (r.ok) return;
    } catch { /* 服务还没起来 */ }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("server did not become healthy");
}

const storeDir = mkdtempSync(path.join(tmpdir(), "shangzhu-e2e-form-"));
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
    fail(`端口 ${PORT} 被旧进程占用，本测试自己的服务没起来（先 kill 旧 uvicorn）`);
    throw new Error(`port ${PORT} occupied by stale server`);
  }
  log("server healthy, launching chromium ...");

  // schema 是本测试的预期来源（不硬编码 25——加字段测试自动跟上）
  const schema = await (await fetch(`${BASE}/form-schema`)).json();
  const expectedFields = schema.input_fields.map((f) => f.name);
  log(`schema input_fields = ${expectedFields.length}`);

  browser = await chromium.launch();
  const page = await browser.newPage();

  const consoleErrors = [];
  const pageErrors = [];
  const clientLogPosts = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => pageErrors.push(String(e)));
  page.on("request", (r) => { if (r.url().endsWith("/client-log")) clientLogPosts.push(r.url()); });

  // 1) 加载 + 新建任务（与 smoke 相同路径）
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForSelector("#task-list", { timeout: 5000 });
  await page.click("#new-task");
  await page.waitForTimeout(1200);

  // 2) 表单已渲染：输入框数 == schema.input_fields 数（schema 驱动契约）
  await page.waitForSelector("#params-list input[data-field]", { timeout: 5000 });
  const domFields = await page.$$eval(
    "#params-list input[data-field]",
    (els) => els.map((e) => e.dataset.field),
  );
  const missing = expectedFields.filter((f) => !domFields.includes(f));
  if (domFields.length !== expectedFields.length || missing.length) {
    fail(`DOM 字段与 schema 不一致: DOM=${domFields.length} schema=${expectedFields.length} 缺=${missing.join(",")}`);
  } else {
    log(`字段数一致: ${domFields.length}`);
  }

  // 3) 缺参字段可填：新任务无参数，客单价输入 15 → 保存 → PUT 200
  // 收入节默认折叠（无值），先按真实用户行为点开节标题（顺带测折叠交互）
  await page.click('#params-list details:has(input[data-field="price_per_unit"]) > summary');
  const putPromise = page.waitForResponse(
    (r) => r.request().method() === "PUT" && /\/tasks\/[^/]+\/params$/.test(r.url()),
    { timeout: 8000 },
  );
  await page.fill("#params-list input[data-field='price_per_unit']", "15");
  await page.click("#params-list .pf-save");
  const putResp = await putPromise;
  if (putResp.status() !== 200) fail(`PUT 状态 ${putResp.status()} != 200`);
  else log("PUT /tasks/{id}/params -> 200");

  // 4) 服务端持久：tasks 列表快照里 price_per_unit === 15
  await page.waitForTimeout(400);
  const tasks = await (await fetch(`${BASE}/tasks`)).json();
  const cur = tasks[0];
  if (!cur || cur.params?.price_per_unit !== 15) {
    fail(`保存未落库: params=${JSON.stringify(cur && cur.params)}`);
  } else {
    log("服务端快照 price_per_unit=15 ✓");
  }

  // 5) 面板回显 [用户] 来源标
  const srcText = await page.textContent("#params-list").catch(() => "");
  if (!srcText.includes("用户")) fail("保存后未显示 [用户] 来源标");
  else log("[用户] 来源标 ✓");

  // 6) 卫生断言
  if (consoleErrors.length) fail(`console errors: ${JSON.stringify(consoleErrors)}`);
  if (pageErrors.length) fail(`uncaught page errors: ${JSON.stringify(pageErrors)}`);
  if (clientLogPosts.length) fail(`前端错误上报被触发: ${clientLogPosts.length} 次`);

  if (process.exitCode !== 1) log(`PASS: fields=${domFields.length}, PUT闭环, 卫生全清`);
} catch (e) {
  fail(String(e && e.stack ? e.stack : e));
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill("SIGTERM");
}
