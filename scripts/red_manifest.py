#!/usr/bin/env python3
"""red_manifest —— 红位核对去模型化（点名抓 v1.2 的机械件，2026-10）。

背景：红先行协议第 3 步"核对红位 == 预测缺口"若由模型读输出下结论，
就是转述——转述是幻觉的唯一入口（模型可以用一句"红位与设计缺口
逐一吻合"覆盖任何真实输出）。本脚本把比较交给代码：预期红位清单进，
精确集合比对出，机器 diff 报告 + 退出码。模型只许粘贴本脚本产出，
不许 paraphrase。

用法（必须用项目 venv python，禁止全局）：
  # 预期全绿（负向验证还原后 / 基线确认）：
  .venv/bin/python3 scripts/red_manifest.py tests/test_form_render_static.py
  # 预期指定红（写红阶段 / 负向验证事故态），逗号分隔，短名或全 nodeid 皆可：
  .venv/bin/python3 scripts/red_manifest.py tests/test_put_params_contract.py \
      -e test_put_without_xhr_403,test_put_404_unknown_task
  # e2e 日志模式（比对对象 = FAIL 行的失败步骤描述）：
  node tests/e2e/form.mjs > /tmp/e2e.log 2>&1
  .venv/bin/python3 scripts/red_manifest.py --log /tmp/e2e.log --expect-steps 字段数一致

退出码：0 = 红位与 manifest 精确一致（含"预期全绿且全绿"）；
        1 = 不一致（少红=断言没牙或点名错；多红=红位错或被别的错误盖住）。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

_FAILED_RE = re.compile(r"^(FAILED|ERROR)\s+(\S+)")
_TAIL_RE = re.compile(r"^=+ .* (?:failed|passed|error).* =+$")


def _match(actual: set[str], expected: set[str]) -> bool:
    """expected 条目允许短名（test_x）或全 nodeid；短名按 :: 后缀匹配。"""
    return actual == expected


def run_pytest(targets: list[str]) -> tuple[set[str], str]:
    """跑 pytest，返回 (实际红 nodeid 集合, 末行统计原文)。"""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--tb=no", "-q", "-rf", *targets],
        capture_output=True, text=True,
    )
    lines = (proc.stdout or "").splitlines()
    red: set[str] = set()
    tail = ""
    for ln in lines:
        m = _FAILED_RE.match(ln.strip())
        if m:
            red.add(m.group(2))
        if " failed" in ln or " passed" in ln or " error" in ln:
            tail = ln.strip()
    return red, tail or "(无统计行——pytest 可能没跑起来，视作意外红)"


def parse_log(path: str) -> set[str]:
    """e2e 模式：提取 FAIL 行的失败描述作为红位标签。"""
    with open(path, encoding="utf-8") as f:
        return {ln.strip() for ln in f if "] FAIL:" in ln}


def report(red: set[str], expected: set[str], mode: str) -> int:
    """机器 diff 报告——这段输出就是模型唯一被允许粘贴的'红位结论'。"""
    print(f"[red-manifest] mode={mode} expected={len(expected)} actual={len(red)}")
    if red == expected:
        print(f"[red-manifest] MATCH=EXACT 红位与预期精确一致（含预期全绿）")
        return 0
    missing = sorted(expected - red)
    unexpected = sorted(red - expected)
    if missing:
        print("[red-manifest] MISSING_RED（点名了却没红——断言没牙 / 点名错 / 被改动顺带修掉）:")
        for m in missing:
            print(f"  - {m}")
    if unexpected:
        print("[red-manifest] UNEXPECTED_RED（没点名却红——红位错 / 被别的错误盖住）:")
        for u in unexpected:
            print(f"  + {u}")
    print("[red-manifest] MATCH=MISMATCH 停下：先解释每个差异，再决定改点名还是改实现")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="红位 manifest 精确比对（禁转述机械件）")
    ap.add_argument("targets", nargs="*", help="pytest 目标（文件/目录/nodeid）")
    ap.add_argument("-e", "--expected", default="", help="预期红 nodeid/test 名，逗号分隔；空=预期全绿")
    ap.add_argument("--log", help="e2e 日志模式：从日志提取 FAIL 行做比对对象")
    ap.add_argument("--expect-steps", default="", help="e2e 模式预期失败步骤描述，逗号分隔（子串匹配）")
    args = ap.parse_args()

    if args.log:
        red = parse_log(args.log)
        expected = set(s.strip() for s in args.expect_steps.split(",") if s.strip())
        # e2e FAIL 行是完整描述：预期条目按子串命中归并
        matched_expected, matched_red = set(), set()
        for e in expected:
            for r in red:
                if e in r:
                    matched_expected.add(e)
                    matched_red.add(r)
        red = red - matched_red
        expected = expected - matched_expected
        # 剩余部分：expected 里没命中的 = MISSING；red 里没归并的 = UNEXPECTED
        return report(red, expected, "e2e-log")

    if not args.targets:
        print("[red-manifest] 缺测试目标（或用 --log 走 e2e 模式）", file=sys.stderr)
        return 2
    red, tail = run_pytest(args.targets)
    expected = set(s.strip() for s in args.expected.split(",") if s.strip())
    # 短名匹配：把 expected 短名归一到实际 nodeid
    norm = set()
    for e in expected:
        hit = [r for r in red if r == e or r.endswith("::" + e)]
        if hit:
            norm.update(hit)
        else:
            norm.add(e)
    print(f"[red-manifest] pytest 尾行原文: {tail}")
    return report(red, norm, "pytest")


if __name__ == "__main__":
    sys.exit(main())
