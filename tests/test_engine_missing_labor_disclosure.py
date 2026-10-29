"""引擎「人工缺失」披露验收（L1 单元契约 · 点名抓 INV-001）。

背景（2026-10-28 抽取层修复 4381dec 后暴露）：
抽取层不再把「客人80人」误落 employee_count，于是 employee_count / avg_salary
缺失的会话显著变多。引擎 `_check_sufficiency` 把人工列为**软缺口**，契约原文是
「按 0 计**并标注**」。实测发现「按 0 计」兑现了（fixed_cost 只算租金），
但「并标注」只落在 basis/gaps，数值本身与状态徽章**没有任何标注**：

    monthly_profit = 31000（人工当 0）  → status.profit = "🟢 盈利"
    daily_breakeven = 16（不含人工）    → be_status   = "🟢 可达保本"

这与 README 的核心主张「绝不把未知当 0 硬算出一个确定的答案」正面冲突：
缺人工却给出确定盈利判定与偏低的保本客流，用户据此做的决策可能是错的。

本文件点名的是「并标注」这一半契约：数值可以继续按 0 近似，但必须让用户在
数字旁边看得到「人工未提供」。

两面用例：
- 缺陷侧（3 条，写实现前必须红）：人工缺失时 利润徽章 / 保本徽章 / 固定成本来源 三处必带标注
- 防误伤侧（2 条，本就该绿）：人工齐全时 确定判定与数值分毫不动

运行：并入 tests/run_all.py；也可 .venv/bin/python3 tests/test_engine_missing_labor_disclosure.py
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tools.workflow_engine import quick_scan
from router.formatter import format_response


def _scan(params: dict) -> dict:
    return json.loads(quick_scan.invoke(
        {"params_json": json.dumps(params, ensure_ascii=False)}))


def _render(params: dict) -> str:
    """用户真正看到的那一层：引擎结果经 formatter 渲染成的 Markdown。"""
    return format_response("quick_scan", _scan(params))


def _profit_row(md: str) -> str:
    """核心指标表里的「月利润」行。

    按行断言而非全文断言：参数表里「未提供」是常态（总投资/阶段等本来就缺），
    全文级判据会把别的字段的缺失误判成人工缺失标注。
    """
    for ln in md.splitlines():
        if ln.startswith("| 月利润 |") and any(m in ln for m in ("🟢", "🟡", "🔴", "⚪")):
            return ln
    return ""


# 客流已从「客人80人」正确抽出，但员工数/薪资未提供 —— 抽取修复后的典型会话
_NO_LABOR = {"industry": "餐饮", "daily_traffic": 80, "price_per_unit": 25,
             "variable_cost_ratio": 0.35, "monthly_rent": 8000}

# 同一场景补上人工（2 人 × 5000）作为防误伤对照
_WITH_LABOR = dict(_NO_LABOR, employee_count=2, avg_salary=5000)

# 缺失标注的措辞判据。注意：不能用「含『人工』二字」当判据——人工齐全时
# 固定成本来源本就是「组件求和(租金[用户] + 人工[用户])」，含「人工」是正常成分。
# 判据必须是「缺失」语义（未提供 / 未计入 / 按 0 计）。
_CAVEAT = "未提供"

# 租金是固定成本的另一主体：缺租金与缺人工完全同构（利润/保本同样被按 0 计），
# 但 INV-001 首轮只修了人工，租金这一侧完全没标注，连 gaps 清单里都没有它。
_NO_RENT = {"industry": "餐饮", "daily_traffic": 80, "price_per_unit": 25,
            "variable_cost_ratio": 0.35, "employee_count": 2, "avg_salary": 5000}

# 键存在但值为 None：workflow_engine 用「键存在」判 labor_present，
# 于是 None 被 `or 0` 吞成 0，人工被伪装成 [推算] 值而非 [缺失]。
_NONE_LABOR_KEY = {"industry": "餐饮", "daily_traffic": 80, "price_per_unit": 25,
                   "variable_cost_ratio": 0.35, "monthly_rent": 8000,
                   "employee_count": None, "avg_salary": 5000}


# ── 缺陷侧：人工缺失时不得给出「确定」判定 ────────────────────────────────

def test_profit_status_not_confident_when_labor_missing():
    """人工缺失时，利润状态不得是确定的 🟢 盈利 / 🔴 亏损，且必须点名人工。"""
    r = _scan(_NO_LABOR)
    status = r["status"]["profit"]
    assert not status.startswith("🟢"), f"人工缺失却给出确定盈利判定：{status}"
    assert not status.startswith("🔴"), f"人工缺失却给出确定亏损判定：{status}"
    assert _CAVEAT in status, f"状态未标注人工缺失：{status}"


def test_breakeven_status_flagged_when_labor_missing():
    """人工缺失时，保本判定不得是确定的 🟢 可达保本（客流门槛被人工抬高）。"""
    r = _scan(_NO_LABOR)
    be = r["status"]["breakeven"]
    assert not be.startswith("🟢"), f"人工缺失却给出确定保本判定：{be}"
    assert _CAVEAT in be, f"保本判定未标注人工缺失：{be}"


def test_fixed_cost_src_annotates_missing_labor():
    """人工缺失时，固定成本的来源标注必须说明人工未计入（而非只算租金了事）。"""
    r = _scan(_NO_LABOR)
    src = r["param_sources"]["monthly_fixed_cost"]
    assert _CAVEAT in src, f"固定成本来源未标注人工缺失：{src}"


def test_rendered_table_not_confident_when_labor_missing():
    """渲染层（用户实际读到的 Markdown）不得给出「🟢 盈利」。

    引擎判定修好还不够：formatter 会**另算一份**利润徽章，若它不读引擎判定，
    用户看到的表格依旧是确定盈利——这是同一缺陷在显示层的第二个出口。
    """
    row = _profit_row(_render(_NO_LABOR))
    assert row, "未找到月利润行"
    assert "🟢 盈利" not in row, f"渲染层仍给出确定盈利判定：{row}"
    assert _CAVEAT in row, f"渲染层未标注人工缺失：{row}"


# ── 防误伤侧：人工齐全时行为分毫不动 ──────────────────────────────────────

def test_labor_present_keeps_confident_profit_status():
    """人工齐全：仍应给出确定盈利判定，且不得出现「按 0 计」类标注。"""
    r = _scan(_WITH_LABOR)
    status = r["status"]["profit"]
    assert status == "🟢 盈利", f"人工齐全时利润判定被改坏：{status}"
    assert _CAVEAT not in status, f"人工齐全却仍带缺失标注：{status}"


def test_rendered_table_confident_when_labor_present():
    """人工齐全：渲染层照旧给出确定盈利，且不带缺失标注。"""
    row = _profit_row(_render(_WITH_LABOR))
    assert row, "未找到月利润行"
    assert "🟢 盈利" in row, f"人工齐全时渲染层判定被改坏：{row}"
    assert _CAVEAT not in row, f"人工齐全却带缺失标注：{row}"


def test_labor_present_metrics_unchanged():
    """人工齐全：利润 21000 / 保本客流约 37，数值与徽章保持原样。"""
    r = _scan(_WITH_LABOR)
    m = r["core_metrics"]
    assert m["monthly_profit"] == 21000, m
    assert 36 <= m["daily_breakeven"] <= 38, m
    assert r["status"]["breakeven"].startswith("🟢"), r["status"]
    assert _CAVEAT not in r["param_sources"]["monthly_fixed_cost"]


# ── 缺陷侧（第二轮）：租金缺失 —— INV-001 的同构实例 ──────────────────────

def test_rent_missing_profit_status_not_confident():
    """缺租金时，利润状态不得是确定的 🟢 盈利 / 🔴 亏损，且必须点名租金。"""
    status = _scan(_NO_RENT)["status"]["profit"]
    assert not status.startswith("🟢"), f"缺租金却给出确定盈利判定：{status}"
    assert not status.startswith("🔴"), f"缺租金却给出确定亏损判定：{status}"
    assert "租金" in status, f"状态未点名租金缺失：{status}"


def test_rent_missing_fixed_cost_src_annotates():
    """缺租金时，固定成本来源标注必须说明租金未计入（不能只写「组件求和(人工)」）。"""
    src = _scan(_NO_RENT)["param_sources"]["monthly_fixed_cost"]
    assert "租金" in src and _CAVEAT in src, f"固定成本来源未标注租金缺失：{src}"


def test_rent_missing_breakeven_flagged():
    """缺租金时，保本判定不得是确定的 🟢 可达保本（固定成本少了租金）。"""
    be = _scan(_NO_RENT)["status"]["breakeven"]
    assert not be.startswith("🟢"), f"缺租金却给出确定保本判定：{be}"
    assert "租金" in be, f"保本判定未点名租金缺失：{be}"


def test_rent_missing_shows_up_in_gaps():
    """缺租金必须出现在「还差这些参数」清单里——门禁拦下时用户看得见的那份。

    注意面选错会假红：gaps 只在 insufficient 路径被渲染，引擎放行（营收已知）时
    quick_scan 输出里根本没有 gaps 键。所以断言必须落在渲染结果上，不能读内部
    结构。这里让营收也缺失，走门禁拦下路径。
    """
    md = _render({"industry": "餐饮", "employee_count": 2, "avg_salary": 5000,
                  "variable_cost_ratio": 0.35})
    assert "还差这些参数" in md, md[:300]
    seg = md.split("还差这些参数", 1)[1].split("##")[0]
    assert "租金" in seg, f"缺口清单里没有租金：{seg[:300]}"


# ── 缺陷侧（第二轮）：None 值不得被 `or 0` 吞成 0 ─────────────────────────

def test_none_valued_employee_count_not_swallowed_to_zero():
    """employee_count 为 None 时，人工必须是「缺失」，不得被 `or 0` 变成 0 还标 [推算]。

    标 [推算] 比标 [缺失] 更危险：它看起来是个有依据的数，实际是缺失伪装的。
    """
    r = _scan(_NONE_LABOR_KEY)
    labor = r["params"].get("monthly_labor")
    src = r["param_sources"].get("monthly_labor", "")
    assert labor is None, f"缺失被吞成数值：monthly_labor={labor}"
    assert src.startswith("[缺失]"), f"缺失被伪装成可信值：{src}"


def test_none_valued_employee_count_profit_not_confident():
    """承上：人工被吞成 0 时，利润徽章不得仍是确定的 🟢 盈利。"""
    status = _scan(_NONE_LABOR_KEY)["status"]["profit"]
    assert not status.startswith("🟢"), f"人工缺失却给出确定盈利判定：{status}"
    assert "人工" in status, f"状态未点名人工缺失：{status}"


# ── 防误伤侧（第二轮）：显式给 0 不等于缺失 ───────────────────────────────

def test_explicit_zero_rent_not_flagged_as_missing():
    """用户明说「租金 0」（在家办公）时，不得报租金缺失——0 是已知值不是未知。"""
    r = _scan(dict(_NO_RENT, monthly_rent=0))
    src = r["param_sources"]["monthly_fixed_cost"]
    assert "租金" not in src or _CAVEAT not in src, f"显式 0 被误报成缺失：{src}"
    assert r["status"]["profit"].startswith("🟢"), r["status"]
