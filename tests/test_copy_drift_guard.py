"""双副本 drift 护栏测试（M-09 分支 B）——脚本不许 bitrot，shangzhu 不许违规。

- scripts/copy_drift_report.py 的 11 条事故形态不变量：shangzhu 全部必须满足；
- 报告脚本必须可运行且 exit 0（EN 侧 drift 只警告不阻塞——EN 是范围外对象）。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import copy_drift_report as cdr  # noqa: E402


def test_shangzhu_satisfies_all_invariants():
    results = cdr.check_copy(cdr.COPIES["shangzhu"])
    violated = {n: d for n, (ok, d) in results.items() if not ok}
    assert not violated, f"shangzhu 违反事故形态不变量: {violated}"


def test_drift_report_runs_clean():
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "copy_drift_report.py")],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert out.returncode == 0, f"drift 报告 exit {out.returncode}（shangzhu 有违规）:\n{out.stdout}{out.stderr}"
    assert "不变量" in out.stdout, "报告输出异常"
