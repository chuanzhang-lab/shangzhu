"""formatter 模板格式化器的直接单测（提升 A 路径覆盖率与防回归）。

覆盖：quick_scan / insufficient / trend / compare / suggest / report / benchmark
各 intent 的格式化输出结构，以及 format_response 对未知 intent 的兜底、
各 formatter 的错误分支（data 含 "error"）与返回类型安全（永远返回 str）。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from router.formatter import (
    format_response,
    _fmt_insufficient,
    _fmt_trend,
    _fmt_compare,
    _fmt_suggest,
    _fmt_report,
    _fmt_benchmark,
)


# ── quick_scan ──────────────────────────────────────────────────────────
def test_fmt_scan_renders_core_metrics():
    data = {
        "core_metrics": {"monthly_profit": 12000, "monthly_revenue": 60000,
                          "daily_breakeven": 50},
        "status": {},
        "param_sources": {"monthly_rent": "[用户]"},
        "params": {"monthly_rent": 8000},
        "project_type": "餐饮",
        "stage": "测算",
    }
    out = format_response("quick_scan", data)
    assert isinstance(out, str)
    assert "月利润" in out
    assert "12,000" in out          # 数值用千分位格式化
    assert "月营收" in out


def test_fmt_scan_error_branch():
    out = _fmt_scan_err({"error": "参数缺失"})
    assert "计算失败" in out


def _fmt_scan_err(data):
    # format_response 会把 quick_scan 错误分支转发到 _fmt_scan 的错误处理
    return format_response("quick_scan", data)


# ── insufficient ────────────────────────────────────────────────────────
def test_fmt_insufficient():
    data = {
        "message": "请补充月营收等核心参数",
        "gaps": ["月营收", "客单价"],
        "coverage": 0.3,
        "framework": {"revenue_model": "客流×单价",
                       "cost_model": "固定+变动",
                       "cash_model": "总投资−月烧钱"},
        "assumptions": [{"field": "monthly_rent", "value": 8000, "source": "[用户]"}],
        "next_step": "补充后重新分析",
    }
    out = _fmt_insufficient(data)
    assert isinstance(out, str)
    assert "参数不足" in out
    assert "月营收" in out
    assert "30%" in out              # coverage 0.3 → 30%


# ── trend ───────────────────────────────────────────────────────────────
def test_fmt_trend():
    data = {
        "months": [{"month": 1, "revenue": 11000, "fixed_cost": 8000,
                    "variable_cost": 4000, "profit": 3000,
                    "cumulative_profit": 3000}],
        "summary": {"月营收": 66000},
    }
    out = _fmt_trend(data)
    assert isinstance(out, str)
    assert "趋势" in out
    assert "11,000" in out


def test_fmt_trend_error_branch():
    out = _fmt_trend({"error": "缺月营收"})
    assert "趋势预测失败" in out


# ── compare ─────────────────────────────────────────────────────────────
def test_fmt_compare():
    data = {
        "base_scenario": {"monthly_profit": 10000, "monthly_revenue": 60000,
                          "monthly_fixed_cost": 20000},
        "alt_scenario": {"monthly_profit": 12000, "monthly_revenue": 70000,
                         "monthly_fixed_cost": 22000},
        "diff": {"verdict": "方案B更优", "profit": 2000},
    }
    out = _fmt_compare(data)
    assert isinstance(out, str)
    assert "方案对比" in out
    assert "方案B更优" in out
    assert "+2,000" in out           # alt−base 利润差


def test_fmt_compare_error_branch():
    out = _fmt_compare({"error": "缺方案数据"})
    assert "对比失败" in out


# ── suggest ─────────────────────────────────────────────────────────────
def test_fmt_suggest():
    data = {
        "issues": [{"severity": "high", "message": "食材成本过高"}],
        "suggestions": [{"target_param": "price", "current": 20, "suggested": 25,
                         "direction": "提价", "rationale": "需求刚性",
                         "expected_profit_delta": 1000}],
        "summary": {"current_monthly_profit": 10000,
                    "projected_monthly_profit": 12000,
                    "total_expected_improvement": 2000,
                    "verdict": "建议提价"},
    }
    out = _fmt_suggest(data)
    assert isinstance(out, str)
    assert "建议" in out
    assert "12,000" in out
    assert "提价" in out


def test_fmt_suggest_error_branch():
    out = _fmt_suggest({"error": "分析失败"})
    assert "参数建议失败" in out


# ── report ───────────────────────────────────────────────────────────────
def test_fmt_report():
    out = _fmt_report({"file_path": "/tmp/report.pdf", "summary": "季度报告"})
    assert isinstance(out, str)
    assert "报告已生成" in out
    assert "/tmp/report.pdf" in out


def test_fmt_report_error_branch():
    out = _fmt_report({"error": "生成失败"})
    assert "报告生成失败" in out


# ── benchmark ────────────────────────────────────────────────────────────
def test_fmt_benchmark():
    out = _fmt_benchmark({"gross_margin": 50, "note": "行业平均"})
    assert isinstance(out, str)
    assert "行业基准" in out


def test_fmt_benchmark_error_branch():
    out = _fmt_benchmark({"error": "查询失败"})
    assert "数据查询失败" in out


# ── format_response 路由兜底 ─────────────────────────────────────────────
def test_format_response_unknown_intent_fallback():
    # 未知 intent 应 json.dumps 兜底，不抛异常、不返回 None
    out = format_response("nonexistent_intent", {"a": 1, "name": "x"})
    assert isinstance(out, str)
    assert '"a"' in out


# ── 健壮性：所有 formatter 对空/缺字段数据都不崩，且返回 str ─────────────
def test_all_formatters_robust_to_empty_data():
    cases = [
        ("quick_scan", {}),
        ("trend", {}),
        ("compare", {}),
        ("suggest", {}),
        ("report_pdf", {}),
        ("report_excel", {}),
        ("benchmark", {}),
    ]
    for intent, data in cases:
        out = format_response(intent, data)
        assert isinstance(out, str), f"{intent} 应返回 str，实际 {type(out)}"
        assert len(out) > 0
