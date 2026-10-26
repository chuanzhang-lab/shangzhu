// 浏览器端到端：AI 解读按钮生命周期 + 前端 abort 预算（fix-ai-advice-timeout-240s-20261008）。
// 断言 A：结构化分析后按钮出现；刷新 + 点任务恢复历史后按钮仍在（历史恢复补挂）。
// 断言 B：/analysis/advice 回包延迟 48s（> 旧 45s 前端 abort）时，前端不得提前放弃：
//         t≈46s 仍在解读中，回包后正常渲染（前端兜底必须晚于后端 240s 预算）。
// 隔离口径与 smoke.mjs 相同：LOCAL_STORE_PATH 临时目录，PGDATABASE_URL 必败地址。
//
// 运行：node tests/e2e/advice.mjs
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

function log(...a) { console.log("[e2e-advice]", ...a); }
function fail(msg) { console.error("[e2e-advice] FAIL:", msg); process.exitCode = 1; }

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

const storeDir = mkdtempSync(path.join(tmpdir(), "shangzhu-e2e-advice-"));
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
  log("server healthy, launching chromium ...");
  browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForSelector("#input", { timeout: 5000 });
  // M-07：本文件测顾问生命周期，不测 NL 输入路径——设「NL 免确认」跳过确认层
  // （默认路径的 e2e 归 confirm.mjs 管），保持参数直接进引擎的原断言口径。
  await page.evaluate(() => localStorage.setItem("nl_confirm_skip", "1"));

  // ── 断言 C：聊天参数变化后，已打开的顾问面板刷新判断 ──
  await page.click("#new-task");
  await page.waitForFunction(
    () => document.querySelectorAll("#task-list .task-item").length > 0,
    { timeout: 5000 },
  );
  let advisorCalls = 0;
  await page.route("**/advisor?tid=*", async (route) => {
    advisorCalls += 1;
    const judgment = advisorCalls === 1
      ? "目前还缺月租和日均客流。"
      : advisorCalls === 3
        ? "新任务的顾问判断。"
        : advisorCalls === 4
          ? "相同参数已为新任务重新判断。"
          : "已读取月租 1800 元、日均客流 80 人。";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        judgment,
        judgment_citations: [],
        risks: [],
        actions: [],
        citations: [],
        params_version: `e2e-${advisorCalls}`,
      }),
    });
  });
  await page.route("**/chat", async (route) => {
    const request = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        content: "参数已更新。",
        thread_id: request.task_id,
        intent: "quick_scan",
        params: { monthly_rent: 1800, daily_traffic: 80 },
        param_sources: { monthly_rent: "[用户]", daily_traffic: "[用户]" },
        derived: [],
        ops_available: false,
        params_version: 1,
      }),
    });
  });
  await page.locator('.params-tab[data-tab="advisor"]').click();
  await page.waitForFunction(
    () => document.querySelector(".advisor-judgment")?.textContent.includes("还缺月租"),
    { timeout: 5000 },
  );
  const refreshedAdvisor = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/advisor" && response.ok(),
  );
  await page.fill("#input", "补充月租和客流");
  await page.click("#send");
  await refreshedAdvisor;
  await page.waitForFunction(
    () => document.querySelector(".advisor-judgment")?.textContent.includes("已读取月租"),
    { timeout: 5000 },
  );
  if (advisorCalls < 2) fail("C: 参数更新后没有重新请求顾问判断");
  else log("C: PASS — 参数更新后顾问判断已刷新");
  const newTaskAdvisor = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/advisor" && response.ok(),
  );
  await page.click("#new-task");
  await newTaskAdvisor;
  await page.waitForFunction(
    () => document.querySelector(".advisor-judgment")?.textContent.includes("新任务的顾问判断"),
    { timeout: 5000 },
  );
  log("C: PASS — 顾问 tab 打开时切换到新任务会加载新判断");
  const repeatedParamsAdvisor = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/advisor" && response.ok(),
  );
  await page.fill("#input", "再次提供相同参数");
  await page.click("#send");
  await repeatedParamsAdvisor;
  await page.waitForFunction(
    () => document.querySelector(".advisor-judgment")?.textContent.includes("相同参数已为新任务重新判断"),
    { timeout: 5000 },
  );
  log("C: PASS — 新任务录入与上一任务相同的数值也会刷新");
  await page.unroute("**/chat");
  await page.unroute("**/advisor?tid=*");
  await page.locator('.params-tab[data-tab="params"]').click();

  // ── 前置：结构化分析，拿到 AI 解读按钮 ──
  await page.fill("#input", "奶茶店月租金1万员工2人工资各5000客单价15日售50杯");
  const analysisRequest = page.waitForRequest((request) => request.url().endsWith("/chat"));
  await page.click("#send");
  const analysisTaskId = (await analysisRequest).postDataJSON().task_id;
  await page.waitForSelector(".advice-btn", { timeout: 15000 });
  log("advice-btn present on fresh analysis message");

  // ── 断言 B：前端 abort 预算 > 45s（拦截回包延迟 48s）──
  // 顺序说明：B 必须在刷新（断言 A）之前跑——否则修复前按钮已消失，B 无从留红记录。
  const slowReply = JSON.stringify({
    status: "ok", text: "延迟回包测试文本", ops: [], ops_block: "",
  });
  await page.route("**/analysis/advice", async (route) => {
    await new Promise((r) => setTimeout(r, 48000));
    await route.fulfill({ status: 200, contentType: "application/json", body: slowReply }).catch(() => {});
  });
  await page.click(".advice-btn");
  const t0 = Date.now();
  await page.waitForTimeout(46000); // 跨过旧 45s abort 窗口
  const midState = await page.evaluate(() => {
    const s = document.querySelector(".ai-advice-status");
    return { cls: s ? s.className : "", text: s ? s.textContent : "" };
  });
  if (!/loading/.test(midState.cls)) {
    fail(`B: t=46s 前端已提前放弃（旧 45s abort 未修）: ${JSON.stringify(midState)}`);
  } else {
    log("B: t=46s still loading — 前端未提前 abort");
    // 等延迟回包落地（48s），断言内容正常渲染
    await page.waitForFunction(
      () => {
        const s = document.querySelector(".ai-advice-status");
        return s && /延迟回包测试文本/.test(s.textContent || "");
      },
      { timeout: 15000 },
    ).then(() => log(`B: PASS — 延迟 ${((Date.now() - t0) / 1000).toFixed(0)}s 的回包正常渲染`))
      .catch(() => fail("B: 48s 回包未渲染（前端 abort 或渲染失败）"));
  }

  // ── 断言 A：按钮出现 → 刷新+恢复历史 → 按钮仍在 ──
  await page.reload({ waitUntil: "networkidle" });
  const analysisTask = `#task-list [data-id="${analysisTaskId}"]`;
  await page.waitForSelector(analysisTask, { timeout: 5000 });
  await page.locator(analysisTask).first().click();
  await page.waitForTimeout(1500);
  const restored = await page.locator(".advice-btn").count();
  if (restored < 1) fail("A: 刷新+任务恢复后 AI 解读按钮消失（历史恢复未补挂）");
  else log("A: PASS — advice-btn re-attached after history restore");

  if (process.exitCode !== 1) log("PASS: 按钮补挂 + 前端 abort 预算 全部通过");
} catch (e) {
  fail(String(e && e.stack ? e.stack : e));
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill("SIGTERM");
}
