#!/usr/bin/env python3
"""双副本 drift 护栏（M-09 分支 B）——事故形态不变量 + 关键文件对比。

背景：shangzhu（中文）与 shangzhu-en（英文）是同构双副本，2026-10-01 事故
「EN 修了、中文版没修」——修复无法自动同步，同一 bug 两个产品各犯一次。

设计取舍（诚实版）：两副本是不同 locale，**全文 hash 永远不同**，直接对比
hash 只会天天红、毫无信息量。因此护栏对比的是「事故形态不变量」——
从真实事故提炼的 11 条 pattern，两副本各自应满足什么一目了然：

- shangzhu 违规 → 硬失败（exit 1，本副本是项目边界内，必须达标）；
- shangzhu-en 违规 → 仅打印 DRIFT 警告（EN 是范围外对象，只读对比不修改，
  其落后/超前状态交由人工决策——归档/合并/跟进，见改进计划 M-09 三分支）。

用法：.venv/bin/python3 scripts/copy_drift_report.py [--json]
"""
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAMILY = os.path.dirname(ROOT)  # shangyezhushou/
COPIES = {
    "shangzhu": ROOT,
    "shangzhu-en": os.path.join(FAMILY, "shangzhu-en"),
}

KEY_FILES = ["web_server.py", "src/web_static/app.js", "tests/conftest.py", "Makefile"]


# ── 事故形态不变量（每条都可追溯到真实事故/计划问题清单）────────────────────
def _read(copy_dir, rel):
    try:
        with open(os.path.join(copy_dir, rel), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def inv_no_hardcoded_asset_ver(copy_dir):
    """不变量1：静态资源版本号不得写死（?v=20260413a 事故形态）。

    只看真实资源引用行（href/src），避免文档/注释里引用历史版本号被误伤。
    """
    src = _read(copy_dir, "web_server.py") or ""
    m = re.findall(r'(?:href|src)="[^"]*\?v=(?!__APP_)[A-Za-z0-9]+', src)
    return (not m, f"发现写死的资源版本号: {m[:3]}" if m else "")


def inv_no_cache_middleware(copy_dir):
    """不变量2：/static 必须有 no-cache 中间件（旧标签页跑旧 JS 的帮凶）。"""
    src = _read(copy_dir, "web_server.py") or ""
    ok = "Cache-Control" in src and "no-cache" in src
    return (ok, "" if ok else "缺 no-cache 中间件")


def inv_no_param_named_t(copy_dir):
    """不变量3：禁止函数参数叫 t（翻译函数遮蔽事故形态）。"""
    src = _read(copy_dir, "src/web_static/app.js") or ""
    bad = [ln.strip() for ln in src.splitlines()
           if re.search(r"function\s+\w+\s*\(\s*t\s*[,)]", ln) or re.search(r"\(\s*t\s*,[^)]*\)\s*=>", ln)]
    return (not bad, f"参数命名 t: {bad[:2]}" if bad else "")


def inv_no_bare_switchtask(copy_dir):
    """不变量4：switchTask 调用必须 await/.catch（无痕失败形态）。"""
    src = _read(copy_dir, "src/web_static/app.js") or ""
    bad = []
    for ln in src.splitlines():
        s = ln.strip()
        if s.startswith("//") or re.match(r"^(async\s+)?function\s+switchTask\s*\(", s):
            continue
        if "switchTask(" in ln and "await switchTask" not in ln and ".catch(" not in ln and not s.startswith("return "):
            bad.append(s)
    return (not bad, f"裸 switchTask: {bad[:2]}" if bad else "")


def inv_health_build_fingerprint(copy_dir):
    """不变量5：/health 暴露构建指纹（static_ver/commit）。"""
    src = _read(copy_dir, "web_server.py") or ""
    ok = "static_ver" in src and "commit" in src
    return (ok, "" if ok else "/health 缺 static_ver/commit 版本握手字段")


def inv_client_log_endpoint(copy_dir):
    """不变量6：前端错误上报端点存在（静默失败可服务端观测）。"""
    src = _read(copy_dir, "web_server.py") or ""
    ok = "/client-log" in src
    return (ok, "" if ok else "缺 /client-log 上报端点")


def inv_test_isolation(copy_dir):
    """不变量7：测试必须有 conftest 隔离（测试写真实库事故形态）。"""
    ok = os.path.isfile(os.path.join(copy_dir, "tests", "conftest.py"))
    return (ok, "" if ok else "缺 tests/conftest.py 测试库隔离")


def inv_lint_gate(copy_dir):
    """不变量8：ESLint 门禁存在。"""
    ok = os.path.isfile(os.path.join(copy_dir, "eslint.config.mjs"))
    return (ok, "" if ok else "缺 eslint.config.mjs 前端门禁")


def inv_ci_gate(copy_dir):
    """不变量9：CI 工作流存在。"""
    ok = os.path.isfile(os.path.join(copy_dir, ".github", "workflows", "ci.yml"))
    return (ok, "" if ok else "缺 .github/workflows/ci.yml")


def inv_e2e_smoke(copy_dir):
    """不变量10：浏览器 e2e 冒烟存在（运行期 TypeError 盲区）。"""
    ok = os.path.isfile(os.path.join(copy_dir, "tests", "e2e", "smoke.mjs"))
    return (ok, "" if ok else "缺 tests/e2e/smoke.mjs 浏览器冒烟")


def inv_report_client_error(copy_dir):
    """不变量11：前端统一错误出口 reportClientError 存在。"""
    src = _read(copy_dir, "src/web_static/app.js") or ""
    ok = "function reportClientError(" in src
    return (ok, "" if ok else "缺 reportClientError 统一错误出口")


INVARIANTS = [
    ("no_hardcoded_asset_ver", inv_no_hardcoded_asset_ver),
    ("no_cache_middleware", inv_no_cache_middleware),
    ("no_param_named_t", inv_no_param_named_t),
    ("no_bare_switchtask", inv_no_bare_switchtask),
    ("health_build_fingerprint", inv_health_build_fingerprint),
    ("client_log_endpoint", inv_client_log_endpoint),
    ("test_isolation", inv_test_isolation),
    ("lint_gate", inv_lint_gate),
    ("ci_gate", inv_ci_gate),
    ("e2e_smoke", inv_e2e_smoke),
    ("report_client_error", inv_report_client_error),
]


def check_copy(copy_dir):
    """返回 {invariant_name: (ok, detail)}。"""
    return {name: fn(copy_dir) for name, fn in INVARIANTS}


def _file_hash(copy_dir, rel):
    try:
        with open(os.path.join(copy_dir, rel), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    except OSError:
        return "missing"


def main():
    as_json = "--json" in sys.argv
    results = {name: check_copy(dir_) for name, dir_ in COPIES.items()}

    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("== 事故形态不变量（11 条）==")
        print(f"{'不变量':<28} {'shangzhu':<10} {'shangzhu-en':<10}")
        for name, _ in INVARIANTS:
            row = []
            for copy in COPIES:
                ok, _detail = results[copy][name]
                row.append("OK" if ok else "VIOLATED")
            print(f"{name:<28} {row[0]:<10} {row[1]:<10}")
        print("\n== 关键文件 hash（全文对比必然不同——locale 不同，仅供参考）==")
        for rel in KEY_FILES:
            hs = [_file_hash(d, rel) for d in COPIES.values()]
            status = "same" if hs[0] == hs[1] and hs[0] != "missing" else "diverged"
            print(f"  {rel:<28} {hs[0]} / {hs[1]}  [{status}]")

    violations = [(name, detail) for name, (ok, detail) in results["shangzhu"].items() if not ok]
    drifts = [(name, detail) for name, (ok, detail) in results["shangzhu-en"].items() if not ok]

    if drifts:
        print("\n[DRIFT 警告] shangzhu-en 未满足（范围外，仅报告，不阻塞）：")
        for name, detail in drifts:
            print(f"  - {name}: {detail}")
    if violations:
        print("\n[违规] shangzhu 未满足（必须修复）：")
        for name, detail in violations:
            print(f"  - {name}: {detail}")
        return 1
    print("\nshangzhu 全部不变量满足 ✓（shangzhu-en drift 见上方警告）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
