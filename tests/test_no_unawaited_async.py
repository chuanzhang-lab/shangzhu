"""未 await/未 catch 的 Promise 调用护栏（M-04，静态扫描）。

背景：`switchTask(...)` 有 3 处裸调用（无 await、无 .catch）——内部抛错连
toast 都没有，纯静默失败，是 2026-10-01 事故排查时确认的排查盲区之一。

规则：`switchTask(` 的调用点（非函数定义）必须满足其一：
- 带 `await`；或
- 同行带 `.catch(`（补上报）；或
- `return` 交给上层处理。

新增其他 async 函数的裸调用检查时，把函数名加进 ASYNC_FUNCS 即可。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(ROOT, "src", "web_static", "app.js")

ASYNC_FUNCS = ["switchTask"]


def _read_lines():
    with open(APP_JS, encoding="utf-8") as f:
        return f.read().splitlines()


def test_no_bare_async_calls():
    offenders = []
    lines = _read_lines()
    for fn in ASYNC_FUNCS:
        call_re = re.compile(rf"(?<!function\s)(?<!\w){fn}\s*\(")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            if re.match(rf"^(async\s+)?function\s+{fn}\s*\(", stripped):
                continue  # 函数定义
            if not call_re.search(line):
                continue
            ok = ("await " + fn) in line or ".catch(" in line or stripped.startswith("return ")
            if not ok:
                offenders.append((i, line.strip()))
    assert not offenders, (
        f"app.js 存在未 await/未 .catch 的异步裸调用（静默失败风险），"
        f"请补 .catch(e => reportClientError(...))：\n"
        + "\n".join(f"  L{i}: {ln}" for i, ln in offenders)
    )


def test_report_client_error_exists():
    """/client-log 上报入口必须存在（异常不吞的前端执行通道）。"""
    src = "\n".join(_read_lines())
    assert "function reportClientError(" in src, "reportClientError 缺失——catch 模板的统一出口没了"
    assert "sendBeacon('/client-log'" in src or 'sendBeacon("/client-log"' in src, \
        "reportClientError 未上报 /client-log——前端错误服务端将不可观测"
