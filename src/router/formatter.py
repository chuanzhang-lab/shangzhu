"""模板格式化器 — 工具结果→人类可读 Markdown

每个工具一种模板。LLM 拿到这个后能润色但不能改关键数字。
"""

import json
from typing import Any, Dict, List, Optional


# ─── 工具: quick_scan ─────────────────────────────────────────────────────
def _fmt_insufficient(data: Dict) -> str:
    """参数不足骨架的渲染：展示缺口 + 模型框架 + 当前假设，不输出误报结论。"""
    lines = []
    lines.append("## ⚠️ 参数不足，已暂停完整分析")
    lines.append("")
    lines.append(data.get("message", "参数不足，暂不输出仪表盘。"))
    lines.append("")

    gaps = data.get("gaps", [])
    if gaps:
        lines.append("## 还差这些参数")
        for g in gaps:
            lines.append(f"- ❓ {g}")
        lines.append("")

    cov = data.get("coverage")
    if cov is not None:
        lines.append(f"参数覆盖率：**{int(cov * 100)}%**")
        lines.append("")

    fw = data.get("framework", {})
    if fw:
        lines.append("## 当前模型框架（仅基于已知输入）")
        lines.append(f"- 收入：{fw.get('revenue_model', '')}")
        lines.append(f"- 成本：{fw.get('cost_model', '')}")
        lines.append(f"- 现金：{fw.get('cash_model', '')}")
        lines.append("")

    # 精确推算层（骨架也展示：能算的照算 + 缺什么）
    lines.extend(_fmt_derived(data.get("derived")))
    if data.get("derived"):
        lines.append("")

    assumptions = data.get("assumptions", [])
    if assumptions:
        lines.append("## 当前假设（补充即可生效）")
        lines.append("| 参数 | 当前值 | 来源 |")
        lines.append("|------|--------|------|")
        for a in assumptions:
            v = a.get("value")
            if v is None:
                v_str = "未知/待填"
            elif isinstance(v, (int, float)) and abs(v) >= 1000:
                v_str = f"{v:,.0f}"
            else:
                v_str = str(v)
            lines.append(f"| {a['field']} | {v_str} | {a['source']} |")
        lines.append("")

    lines.append("---")
    lines.append(data.get("next_step", "补充上述参数后重新分析。"))
    return "\n".join(lines)


def _fmt_derived(derived) -> list:
    """精确推算层渲染：由用户输入 + 确定公式推出的关联参数，逐项带公式标注。

    无「默认值」——每项要么已精确算出（ok），要么缺输入（missing，附缺什么）。
    返回 markdown 行列表。
    """
    derived = derived or []
    if not derived:
        return []
    ok_items = [d for d in derived if d.get("status") == "ok"]
    miss_items = [d for d in derived if d.get("status") == "missing"]
    out = ["## 📐 精确推算（由你输入按公式推出，非猜测）", ""]
    if ok_items:
        out.append("| 参数 | 推算值 | 公式 |")
        out.append("|------|--------|------|")
        for d in ok_items:
            val = d["value"]
            vs = f"{val:,.0f} {d['unit']}" if isinstance(val, (int, float)) else str(val)
            out.append(f"| {d['label']} | {vs} | `{d['formula']}` |")
        out.append("")
    if miss_items:
        out.append("**暂不能推算**（缺输入）：")
        out.append("")
        for d in miss_items:
            out.append(f"- {d['label']}：缺 **{d.get('missing', '未知')}**（`{d['formula']}`）")
        out.append("")
    return out


def _fmt_scan(data: Dict) -> str:
    if "error" in data:
        return f"## ⚠️ 计算失败\n\n{data['error']}\n\n请检查参数是否正确（如月租、客流、单价等）。"

    # 参数不足骨架（决策B：门禁拦下时的呈现）
    if data.get("insufficient"):
        return _fmt_insufficient(data)

    core = data.get("core_metrics", {})
    status = data.get("status", {})
    params_src = data.get("param_sources", {})
    sensitivity = data.get("sensitivity", {}).get("scenarios", [])
    pitfalls = data.get("pitfalls", {}).get("pitfalls", [])
    bench = data.get("benchmark", {})

    lines = []

    # 标题 + 项目类型
    project_type = data.get("project_type", "项目")
    stage = data.get("stage", "")
    template_mode = data.get("template_mode", "")
    if template_mode:
        lines.append(f"## 📊 {project_type}分析（{stage} · {template_mode}）")
    else:
        lines.append(f"## 📊 {project_type}分析（{stage}）")
    lines.append("")

    # 数据冲突（派生一致性）：规则层先发现，前置高亮，不依赖 LLM
    derived_issues = data.get("derived_issues") or []
    if derived_issues:
        lines.append("## ⚠️ 数据冲突（请确认口径）")
        for i in derived_issues:
            lines.append(f"> {i.get('message', '')}")
        lines.append("")

    # 核心指标
    lines.append("## 核心指标")
    lines.append("| 指标 | 数值 | 状态 |")
    lines.append("|------|------|------|")

    # D2：变动成本率缺失 → 利润/毛利率「还不能定」，先给出缺什么再展示其余
    vc_gap = core.get("monthly_profit") is None
    if vc_gap:
        lines.append("> 📌 **变动成本率未提供，利润与保本结论还不能定。**")
        lines.append("> 补一句「变动成本率 55%」或「每份成本 X 元」即可算出硬结论。")
        lines.append("")

    monthly_profit = core.get("monthly_profit", 0)
    if monthly_profit is None:
        profit_status = "⚪ 未知（需变动成本率）"
    else:
        profit_status = "🟢 盈利" if monthly_profit > 0 else "🔴 亏损"
    lines.append(f"| 月利润 | {'—' if monthly_profit is None else f'{monthly_profit:,.0f} 元'} | {profit_status} |")

    monthly_revenue = core.get("monthly_revenue")
    rev_str = f"{monthly_revenue:,.0f} 元" if isinstance(monthly_revenue, (int, float)) else "—"
    lines.append(f"| 月营收 | {rev_str} | — |")

    daily_breakeven = core.get("daily_breakeven")
    if daily_breakeven:
        lines.append(f"| 盈亏平衡客流 | {daily_breakeven:.0f} 杯/天 | — |")

    gross_margin = core.get("gross_margin_percent")
    if gross_margin:
        lines.append(f"| 毛利率 | {gross_margin}% | — |")

    runway = core.get("runway_months")
    if runway is not None and runway != "无限":
        lines.append(f"| 跑道 | {runway} 月 | — |")
    elif runway is None:
        lines.append(f"| 跑道 | 未知（需总投资） | — |")

    lines.append("")

    # 精确推算层：把「由你输入用公式推出」的关联参数逐项列出（带公式，无猜测）
    lines.extend(_fmt_derived(data.get("derived")))

    lines.append("")

    # 风险聚焦（⑤ 叙事>判决：把杠杆点交还用户，而非只给一个 🔴危险）
    narrative = data.get("narrative")
    if narrative:
        lines.append("## 🎯 风险聚焦")
        lines.append(f"> {narrative}")
        lines.append("")

    # 参数来源
    params_data = data.get("params", {})
    if params_src:
        lines.append("## 参数（来源）")
        lines.append("| 参数 | 值 | 来源 |")
        lines.append("|------|-----|------|")
        for k, src in params_src.items():
            if src and not k.startswith("_"):
                val = params_data.get(k, "")
                if val == "" or val is None:
                    if src.startswith("[缺失]"):
                        val_str = "未知/待填"   # [缺失] 字段明确标出，而非静默跳过
                    else:
                        continue
                elif isinstance(val, (int, float)):
                    val_str = f"{val:,.0f}" if val >= 1000 else str(val)
                else:
                    val_str = str(val)
                lines.append(f"| {k} | {val_str} | {src} |")
        lines.append("")

    # 当前假设清单（决策A③：把默认/缺失假设前置可见）
    assumptions = data.get("assumptions")
    if assumptions:
        lines.append("## 当前假设（补充即可生效）")
        lines.append("| 参数 | 当前值 | 来源 |")
        lines.append("|------|--------|------|")
        for a in assumptions:
            v = a.get("value")
            if v is None:
                v_str = "未知/待填"
            elif isinstance(v, (int, float)) and abs(v) >= 1000:
                v_str = f"{v:,.0f}"
            else:
                v_str = str(v)
            lines.append(f"| {a['field']} | {v_str} | {a['source']} |")
        lines.append("")

    # 情景分析（③⑥ 输出范围而非单点；把"未知"变成结论的弹性）
    scenarios = data.get("scenarios")
    if scenarios and scenarios.get("has_uncertainty"):
        sp = scenarios.get("monthly_profit", {})
        rw = scenarios.get("runway", {})
        def _fmt_num(v):
            if v is None:
                return "未知"
            if isinstance(v, (int, float)):
                return f"{v:,.0f}"
            return str(v)
        lines.append("## 📊 情景分析（乐观 / 中性 / 保守）")
        lines.append("> 不是给你一个死数字，而是「取决于哪些假设」的区间。")
        lines.append("")
        lines.append("| 指标 | 保守 | 中性 | 乐观 |")
        lines.append("|------|------|------|------|")
        lines.append(f"| 月利润 | {_fmt_num(sp.get('worst'))} | {_fmt_num(sp.get('base'))} | {_fmt_num(sp.get('best'))} |")
        lines.append(f"| 跑道(月) | {_fmt_num(rw.get('worst'))} | {_fmt_num(rw.get('base'))} | {_fmt_num(rw.get('best'))} |")
        drivers = scenarios.get("drivers", [])
        if drivers:
            lines.append("")
            lines.append("区间由这些**未确认假设**驱动：" + "、".join(f"「{d}」" for d in drivers))
        lines.append("")

    # 敏感性分析
    if sensitivity:
        lines.append("## 敏感性分析")
        lines.append("| 场景 | 营收 | 成本 | 月利润 |")
        lines.append("|------|------|------|--------|")
        for s in sensitivity[:3]:
            rev = s.get("revenue_change", "0%")
            cost = s.get("cost_change", "0%")
            profit = s.get("profit", 0)
            lines.append(f"| {s.get('scenario', '?')} | {rev} | {cost} | {profit:,.0f} |")
        lines.append("")

    # 风险
    if pitfalls:
        lines.append("## 风险")
        lines.append("| 级别 | 风险 |")
        lines.append("|------|------|")
        severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
        for p in pitfalls[:5]:
            sev = p.get("severity", "medium")
            emoji = severity_emoji.get(sev, "⚪")
            title = p.get("title", "")
            lines.append(f"| {emoji} {sev} | {title} |")
        lines.append("")

    # Benchmark
    if bench and isinstance(bench, dict) and bench:
        lines.append("## 行业参考")
        for k, v in bench.items():
            if isinstance(v, (int, float)):
                lines.append(f"- {k}: {v}")
            elif isinstance(v, str):
                lines.append(f"- {k}: {v}")
        lines.append("")

    # 操作提示
    lines.append("---")
    lines.append("操作: 改参数 | 趋势预测 | 对比方案 | 参数建议 | 生成PDF")

    return "\n".join(lines)


# ─── 工具: trend_projection ──────────────────────────────────────────────
def _fmt_trend(data: Dict) -> str:
    if "error" in data:
        return f"## ⚠️ 趋势预测失败\n\n{data['error']}"

    # ④：稀疏输入（无月营收）下走骨架渲染，不静默展示全负值误报趋势
    if data.get("insufficient"):
        return _fmt_insufficient(data)

    months = data.get("months", [])
    summary = data.get("summary", {})

    lines = []
    lines.append("## 📈 12个月趋势预测")
    lines.append("")

    # 摘要
    if summary:
        lines.append("## 摘要")
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        for k, v in summary.items():
            v_str = f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)
            lines.append(f"| {k} | {v_str} |")
        lines.append("")

    # 月度数据
    if months:
        lines.append("## 月度明细")
        lines.append("| 月 | 营收 | 固定成本 | 变动成本 | 利润 | 累计 |")
        lines.append("|----|------|----------|----------|------|------|")
        for m in months:
            lines.append(
                f"| {m.get('month', '?')} | "
                f"{m.get('revenue', 0):,.0f} | "
                f"{m.get('fixed_cost', 0):,.0f} | "
                f"{m.get('variable_cost', 0):,.0f} | "
                f"{m.get('profit', 0):,.0f} | "
                f"{m.get('cumulative_profit', 0):,.0f} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("操作: 改参数 | 重新算 | 对比方案 | 参数建议")

    return "\n".join(lines)


# ─── 工具: compare_scenarios ─────────────────────────────────────────────
def _fmt_compare(data: Dict) -> str:
    if "error" in data:
        return f"## ⚠️ 对比失败\n\n{data['error']}"

    # ④：任一方方案缺月营收时走骨架渲染
    if data.get("insufficient"):
        return _fmt_insufficient(data)

    base = data.get("base_scenario", {})
    alt = data.get("alt_scenario", {})
    diff = data.get("diff", {})

    lines = []
    lines.append("## 🔀 方案对比")
    lines.append("")

    # 并排
    lines.append("| 指标 | 方案A | 方案B | 差异 |")
    lines.append("|------|-------|-------|------|")

    # 利润
    base_profit = base.get("monthly_profit", 0)
    alt_profit = alt.get("monthly_profit", 0)
    lines.append(f"| 月利润 | {base_profit:,.0f} | {alt_profit:,.0f} | {alt_profit - base_profit:+,.0f} |")

    # 营收
    base_rev = base.get("monthly_revenue", 0)
    alt_rev = alt.get("monthly_revenue", 0)
    lines.append(f"| 月营收 | {base_rev:,.0f} | {alt_rev:,.0f} | {alt_rev - base_rev:+,.0f} |")

    # 固定成本
    base_fix = base.get("monthly_fixed_cost", 0)
    alt_fix = alt.get("monthly_fixed_cost", 0)
    lines.append(f"| 月固定成本 | {base_fix:,.0f} | {alt_fix:,.0f} | {alt_fix - base_fix:+,.0f} |")

    lines.append("")

    # 结论
    if diff.get("verdict"):
        lines.append(f"## 结论: {diff['verdict']}")
        if "profit" in diff:
            lines.append(f"\n利润差异: {diff['profit']:+,.0f} 元/月")
        if "revenue" in diff:
            lines.append(f"营收差异: {diff['revenue']:+,.0f} 元/月")
        lines.append("")

    lines.append("---")
    lines.append("操作: 改参数 | 趋势预测 | 参数建议 | 生成PDF")

    return "\n".join(lines)


# ─── 工具: suggest_params ────────────────────────────────────────────────
def _fmt_suggest(data: Dict) -> str:
    if "error" in data:
        return f"## ⚠️ 参数建议失败\n\n{data['error']}"

    issues = data.get("issues", [])
    suggestions = data.get("suggestions", [])
    summary = data.get("summary", {})

    lines = []
    lines.append("## 💡 参数调整建议")
    lines.append("")

    # 核心指标
    if summary:
        cur = summary.get("current_monthly_profit", 0)
        new = summary.get("projected_monthly_profit", 0)
        improvement = summary.get("total_expected_improvement", 0)
        verdict = summary.get("verdict", "")

        lines.append("## 调整后预期")
        lines.append(f"- 当前月利润: **{cur:,.0f} 元**")
        lines.append(f"- 调整后月利润: **{new:,.0f} 元**")
        lines.append(f"- 总改善: **{improvement:,.0f} 元/月**")
        if verdict:
            lines.append(f"- 结论: {verdict}")
        lines.append("")

    # 问题
    if issues:
        lines.append("## 检测到的问题")
        lines.append("| 严重度 | 问题 |")
        lines.append("|--------|------|")
        severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}
        for issue in issues:
            sev = issue.get("severity", "medium")
            emoji = severity_emoji.get(sev, "⚪")
            lines.append(f"| {emoji} {sev} | {issue.get('message', '')} |")
        lines.append("")

    # 建议
    if suggestions:
        lines.append("## 调整建议")
        lines.append("| 参数 | 当前 | 建议 | 方向 | 理由 | 预估利润改善 |")
        lines.append("|------|------|------|------|------|------------|")
        for s in suggestions:
            target = s.get("target_param", "")
            current = s.get("current", "")
            suggested = s.get("suggested", "")
            direction = s.get("direction", "")
            rationale = s.get("rationale", "")
            delta = s.get("expected_profit_delta", 0)
            delta_str = f"+{delta:,.0f} 元" if delta > 0 else "—"
            # 转 int 显示更整洁
            if isinstance(current, float) and current.is_integer():
                current = int(current)
            if isinstance(suggested, float) and suggested.is_integer():
                suggested = int(suggested)
            lines.append(f"| {target} | {current} | {suggested} | {direction} | {rationale} | {delta_str} |")
        lines.append("")

    lines.append("---")
    lines.append("操作: 改参数试试 | 对比方案 | 趋势预测 | 生成PDF")
    lines.append("")
    lines.append("> 💡 建议从「影响最大 + 改动最小」的方向开始。")

    return "\n".join(lines)


# ─── 工具: report ─────────────────────────────────────────────────────────
def _fmt_report(data: Dict) -> str:
    if "error" in data:
        return f"## ⚠️ 报告生成失败\n\n{data['error']}"

    lines = []
    lines.append("## 📄 报告生成")
    lines.append("")

    file_path = data.get("file_path") or data.get("url") or data.get("path")
    if file_path:
        lines.append(f"报告已生成: `{file_path}`")
    else:
        lines.append("报告已生成。")

    # 摘要
    if data.get("summary"):
        lines.append("")
        lines.append(str(data["summary"]))

    return "\n".join(lines)


# ─── 工具: benchmark ──────────────────────────────────────────────────────
def _fmt_benchmark(data: Dict) -> str:
    if "error" in data:
        return f"## ⚠️ 数据查询失败\n\n{data['error']}"

    lines = []
    lines.append("## 📚 行业基准数据")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(data, ensure_ascii=False, indent=2))
    lines.append("```")

    return "\n".join(lines)


# ─── L2 决策 ────────────────────────────────────────────────────────────

def _fmt_decision(data: Dict) -> str:
    """L2 决策结果渲染（决策输出规范 4.3：客观结构 + 一次性验证建议，无倾向）。"""
    from decision_engine import render_decision
    return render_decision(data)


# ─── 现金流明细表（档 B）────────────────────────────────────────────────

def _fmt_cashflow(data: Dict) -> str:
    """月现金流明细表渲染。

    缺期初现金/营收 → 「还不能定」+ 补什么；否则 12 行明细 + 归零月/累计缺口。
    """
    if "error" in data:
        return f"## ⚠️ 现金流计算失败\n\n{data['error']}\n\n请检查期初现金（总投资）与月营收是否提供。"
    if data.get("insufficient"):
        md = ["## 💧 现金流还不能定", ""]
        md.append("期初现金或月营收未提供，无法给出确定性现金流明细。")
        for g in data.get("gaps", []):
            md.append(f"- 补充：{g}")
        return "\n".join(md)

    md = ["## 💧 现金流明细（12 个月）", ""]
    project_type = data.get("project_type") or "项目"
    md.append(f"**{project_type}** · 期初现金 = {_fmt_num_cf(data.get('opening_now'))}（总投资推导）")
    if data.get("notes"):
        md.append("")
        md.extend(f"- {n}" for n in data["notes"])
    md.append("")
    md.append("| 月 | 收入到账 | 支出 | 净额 | 月末现金 |")
    md.append("|----|---------|------|------|---------|")
    schedule = data.get("schedule", [])
    for row in schedule:
        md.append(
            f"| {row['month']} | {_fmt_num_cf(row['inflow'])} | {_fmt_num_cf(row['outflow'])} "
            f"| {_fmt_num_cf(row['net'])} | {_fmt_num_cf(row['closing'])} |"
        )
    md.append("")

    zc = data.get("zero_cash_month")
    if zc is not None:
        md.append(f"📉 **现金归零**：无外部注资下，现金约在第 **{zc} 个月**耗尽。")
    else:
        md.append("🟢 **12 个月内现金未耗尽**（基于当前输入；假设若变结论动）。")
    ms = data.get("max_shortfall")
    if ms is not None:
        md.append(f"💰 **累计最大缺口**：约 **{ms:,.0f} 元**（在归零月之后的缺口）。")
    md.append("")
    md.append("> 现金流只关注「实际到账/支出」（含一次性大额、到账延迟、季度支付），与利润（P&L）解耦。")
    return "\n".join(md)


def _fmt_num_cf(v) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)


# ─── 路由 ────────────────────────────────────────────────────────────────
_FORMATTERS = {
    "quick_scan": _fmt_scan,
    "trend": _fmt_trend,
    "compare": _fmt_compare,
    "suggest": _fmt_suggest,
    "decide": _fmt_decision,
    "cashflow": _fmt_cashflow,
    "report_pdf": _fmt_report,
    "report_excel": _fmt_report,
    "benchmark": _fmt_benchmark,
    "market": _fmt_benchmark,  # 临时复用
}


def format_response(intent: str, tool_data: Dict) -> str:
    """根据意图和工具数据，返回 Markdown 字符串。"""
    formatter = _FORMATTERS.get(intent)
    if formatter is None:
        return json.dumps(tool_data, ensure_ascii=False, indent=2)
    return formatter(tool_data)
