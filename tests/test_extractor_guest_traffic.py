"""M-02 抽取器两面用例：客人/到店语境分流 + 「N人/天」禁双写。

背景（2026-10 线上事故，probe_zh_extract.py Part 1 实证）：
- 「客人80人」→ employee_count=80（用户从未说过员工数，系统替他编了一个，
  还带着「超出常见区间」的守门警告）；
- 「50 人/天」→ daily_traffic=50 **且** employee_count=50 双写（后写覆盖
  先写，第 4 轮把真员工数 80 洗成 50）；
- 根因：_HEADCOUNT_RE 的负向断言只有 均|次|创，任何「N人」形态一律落
  employee_count，与语境无关。

两面用例（执行简报规定）：修复必须同时守住两侧——
- 防误拦侧：请两个人 / 员工80人 / 招3人 / 2个员工每人6000 必须照旧成立；
- 防误抽侧：客人80人 / 50 人/天 / 每天50人 / 来了80人 / 每天来80个客人
  / 80个客人 不得进 employee_count，客流落 daily_traffic。

回归护栏：新增「客人」语境识别不得吃掉钱的语境（客人平均消费50元）。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from router.param_extractor import extract_params  # noqa: E402

# ── 防误拦侧（当前已绿，修复后必须仍然绿）+ 防误抽侧（当前红，修复后转绿）──
ROUTE_CASES = [
    # 防误拦：雇佣语境照旧进 employee_count
    ("请两个人", {"employee_count": 2}),
    ("员工80人", {"employee_count": 80}),
    ("招3人", {"employee_count": 3}),
    ("2个员工每人6000", {"employee_count": 2, "avg_salary": 6000}),
    # 防误抽：客人/到店/每天语境进 daily_traffic
    ("客人80人", {"daily_traffic": 80}),
    ("50 人/天", {"daily_traffic": 50}),
    ("每天50人", {"daily_traffic": 50}),
    ("来了80人", {"daily_traffic": 80}),
    ("每天来80个客人", {"daily_traffic": 80}),
    ("80个客人", {"daily_traffic": 80}),
]


@pytest.mark.parametrize("text,expected", ROUTE_CASES)
def test_route_and_hold(text, expected):
    p = extract_params(text)
    for k, v in expected.items():
        got = p.get(k)
        assert got == v, f"{text!r}: 期望 {k}={v}, 实得 {got} (全量: {p})"


# ── 禁双写：客流语境下 employee_count 不得出现（事故同形态）──
FORBIDDEN_CASES = [
    ("客人80人", "employee_count"),
    ("50 人/天", "employee_count"),
    ("每天50人", "employee_count"),
    ("来了80人", "employee_count"),
    ("每天来80个客人", "employee_count"),
    ("80个客人", "employee_count"),
]


@pytest.mark.parametrize("text,field", FORBIDDEN_CASES)
def test_no_employee_double_write(text, field):
    p = extract_params(text)
    assert field not in p, f"{text!r} 不得写 {field} (全量: {p})"


def test_guest_price_context_not_eaten():
    """客人语境识别的回归护栏：钱的语境必须拒收为客流。"""
    p1 = extract_params("客人平均消费50元")
    assert "daily_traffic" not in p1, f"客单价被吃成客流: {p1}"
    p2 = extract_params("每位客人消费30元")
    assert "daily_traffic" not in p2, f"客单价被吃成客流: {p2}"
