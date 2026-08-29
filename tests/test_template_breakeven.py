"""12 个行业模板 × 新增参数 + 修改参数 + 收支平衡建议 全面测试。

测试目标（用户要求）：
  1. 对每个行业模板都跑一次；
  2. 每次测试都包含「新增参数」（模板原本没有、引擎支持的字段）与
     「修改参数」（覆盖模板默认值）；
  3. 输出必须包含「收支平衡的建议」（breakeven 模块 + daily_breakeven + status.breakeven）；
  4. 测试后确认每个模板都正常运行（无 error、模板已应用、关键字段齐全）。

运行：
    .venv/bin/python3 tests/run_all.py        # 作为 t10 进入统一套件
    uv run pytest tests/test_template_breakeven.py
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tools.workflow_engine import (
    INDUSTRY_TEMPLATES,
    FALLBACK_TEMPLATE,
    quick_scan,
)

# 报告累积（供最后的汇总测试写出 markdown）
_REPORT_ROWS = []


def _scan(json_str: str) -> dict:
    return json.loads(quick_scan.invoke({"params_json": json_str}))


def build_case(industry: str, tpl: dict) -> dict:
    """构造一个「带新增参数 + 修改参数」的测试输入。

    - 修改参数：覆盖模板默认值（employee_count / avg_salary / variable_cost_ratio），
      用于验证模板默认值可被用户覆盖且来源标注为 [用户]。
    - 新增参数：模板里原本没有、但引擎支持的字段
      （daily_traffic / price_per_unit / total_investment / monthly_rent /
      融资 / 创始人 / 城市 / 竞品 / 增长 / 季节 / 阶段 / TAM / 点位）。
    """
    # ── 修改参数：在模板默认基础上做调整，保证「确实变了」且仍合法 ──
    if tpl["variable_cost_ratio"] > 0.3:
        mod_vc = round(tpl["variable_cost_ratio"] - 0.05, 2)   # 制造 0.65→0.60 等
    else:
        mod_vc = round(tpl["variable_cost_ratio"] + 0.05, 2)   # 金融 0.15→0.20 等
    mod_salary = int(tpl["avg_salary"] * 1.1)                  # 上调 10%
    mod_staff = tpl["employee_count"] + 1                      # 多招 1 人

    # ── 新增参数：模板里没有、引擎支持 ──
    params = {
        "industry": industry,
        # —— 修改参数（覆盖模板默认）——
        "employee_count": mod_staff,
        "avg_salary": mod_salary,
        "variable_cost_ratio": mod_vc,
        # —— 新增参数（模板不含）——
        "daily_traffic": 120,
        "price_per_unit": 35,
        "total_investment": 300000,
        "monthly_rent": 12000,
        "has_financing": True,
        "funding_round": "天使轮",
        "funding_amount": 800000,
        "founder_count": 2,
        "has_tech_cofounder": True,
        "has_market_cofounder": True,
        "has_ops_cofounder": False,
        "city": "上海",
        "competitor_count": 6,
        "monthly_growth_rate": 0.08,
        "seasonal_factor": 1.1,
        "stage": "验证期",
        "tam_description": "目标市场约 50 亿元",
        "location_type": "核心商圈",
    }
    return params


def run_one(industry: str) -> dict:
    """运行单个行业模板，返回结构化结果（含断言信息）。"""
    tpl = INDUSTRY_TEMPLATES[industry]
    params = build_case(industry, tpl)
    raw = _scan(json.dumps(params, ensure_ascii=False))

    # —— 断言：正常运行 ——
    assert "error" not in raw, f"{industry} 返回 error: {raw.get('error')}"
    assert raw.get("template_applied") is True, f"{industry} 模板未应用"
    assert raw.get("insufficient") is not True, f"{industry} 被误判不充分（参数已齐）"

    # —— 断言：修改参数确实覆盖模板默认（来源=[用户]）——
    src = raw.get("param_sources", {})
    assert src.get("employee_count", "").startswith("[用户]"), \
        f"{industry} employee_count 未标记为[用户]（修改参数未生效）"
    assert src.get("avg_salary", "").startswith("[用户]"), \
        f"{industry} avg_salary 未标记为[用户]（修改参数未生效）"
    assert src.get("variable_cost_ratio", "").startswith("[用户]"), \
        f"{industry} variable_cost_ratio 未标记为[用户]（修改参数未生效）"

    # —— 断言：新增参数被引擎采纳（出现在输出）——
    out_params = raw.get("params", {})
    assert out_params.get("city") == "上海", f"{industry} 新增参数 city 未写入输出"
    assert out_params.get("founder_count") == 2, f"{industry} 新增参数 founder_count 未写入输出"

    # —— 断言：收支平衡的建议存在 ——
    be = raw.get("breakeven", {})
    assert isinstance(be, dict) and "error" not in be, \
        f"{industry} 收支平衡模块异常: {be}"
    assert be.get("breakeven_units", 0) > 0, f"{industry} 未给出保本销量"
    assert be.get("breakeven_revenue", 0) > 0, f"{industry} 未给出保本收入"
    core = raw.get("core_metrics", {})
    assert "daily_breakeven" in core, f"{industry} 缺 daily_breakeven"
    status = raw.get("status", {})
    assert status.get("breakeven"), f"{industry} 缺 status.breakeven 建议"

    # —— 断言：中等增强字段存在（benchmark 真实对比 + 行业成本结构）——
    assert isinstance(raw.get("benchmark_check"), list), f"{industry} 缺 benchmark_check"
    cs = raw.get("industry_cost_structure", {})
    assert isinstance(cs, dict) and abs(sum(cs.values()) - 1.0) < 1e-6, \
        f"{industry} 行业成本结构占比未归一: {cs}"
    # 模板不再含死字段 gross_margin（毛利率改由 variable_cost_ratio 推导）
    assert "gross_margin" not in tpl, f"{industry} 模板仍含死字段 gross_margin"

    return {
        "industry": industry,
        "template_mode": raw.get("template_mode", ""),
        "modified": {
            "employee_count": f"{tpl['employee_count']} → {params['employee_count']}",
            "avg_salary": f"{tpl['avg_salary']} → {params['avg_salary']}",
            "variable_cost_ratio": f"{tpl['variable_cost_ratio']} → {params['variable_cost_ratio']}",
        },
        "new_params": {
            "daily_traffic": params["daily_traffic"],
            "price_per_unit": params["price_per_unit"],
            "total_investment": params["total_investment"],
            "monthly_rent": params["monthly_rent"],
            "has_financing": f"{params['funding_round']} {params['funding_amount']}",
            "founder_count": params["founder_count"],
            "city": params["city"],
            "competitor_count": params["competitor_count"],
            "monthly_growth_rate": params["monthly_growth_rate"],
            "seasonal_factor": params["seasonal_factor"],
            "stage": params["stage"],
            "location_type": params["location_type"],
        },
        "breakeven_advice": {
            "breakeven_units": be.get("breakeven_units"),
            "breakeven_revenue": be.get("breakeven_revenue"),
            "daily_breakeven": core.get("daily_breakeven"),
            "contribution_margin": be.get("contribution_margin_per_unit"),
            "status": status.get("breakeven"),
        },
        "profit_status": status.get("profit"),
        "cash_status": status.get("cash"),
        "raw": raw,
    }


# ─── 为每个行业生成独立测试用例（编号保证执行顺序 + 可见性）──
_INDUSTRIES = list(INDUSTRY_TEMPLATES.keys())


def _make_test(idx: int, industry: str):
    def test_fn():
        res = run_one(industry)
        _REPORT_ROWS.append(res)  # 累积到报告
    test_fn.__name__ = f"test_template_{idx:02d}_{industry}"
    return test_fn


# 动态注册 12 个测试函数
for _i, _ind in enumerate(_INDUSTRIES, start=1):
    globals()[f"test_template_{_i:02d}_{_ind}"] = _make_test(_i, _ind)


def test_template_report():
    """汇总：写出 markdown 报告并做整体断言（在所有行业测试之后运行）。"""
    assert _REPORT_ROWS, "没有收集到任何模板测试结果"
    assert len(_REPORT_ROWS) == len(_INDUSTRIES), \
        f"仅测试了 {len(_REPORT_ROWS)}/{len(_INDUSTRIES)} 个模板"

    lines = []
    lines.append("# 行业模板测试报告（新增参数 + 修改参数 + 收支平衡建议）\n")
    lines.append(f"**测试时间**：2026-07-13  ")
    lines.append(f"**覆盖模板数**：{len(_REPORT_ROWS)} / {len(_INDUSTRIES)}（全部行业模板）  ")
    lines.append("**测试要求**：每个模板都含 新增参数、修改参数、收支平衡建议，并确认正常运行。\n")

    lines.append("## 一、逐模板明细\n")
    for r in _REPORT_ROWS:
        lines.append(f"### {r['industry']}  —  {r['template_mode']}\n")
        lines.append("**✅ 运行结果**：正常（无 error，模板已应用，关键字段齐全）\n")

        lines.append("**🆕 新增参数（模板原本没有、引擎支持）**\n")
        lines.append("| 参数 | 取值 |")
        lines.append("| --- | --- |")
        for k, v in r["new_params"].items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

        lines.append("**✏️ 修改参数（覆盖模板默认值，来源标记 [用户]）**\n")
        lines.append("| 参数 | 模板默认 → 测试取值 |")
        lines.append("| --- | --- |")
        for k, v in r["modified"].items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

        be = r["breakeven_advice"]
        lines.append("**⚖️ 收支平衡的建议**\n")
        lines.append(f"- 保本销量：**{be['breakeven_units']} 单位/年**")
        lines.append(f"- 保本收入：**¥{be['breakeven_revenue']:,}**")
        lines.append(f"- 日均保本：**{be['daily_breakeven']} 单位/天**")
        lines.append(f"- 单位边际贡献：**¥{be['contribution_margin']}**")
        lines.append(f"- 保本判定：**{be['status']}**")
        lines.append(f"- 盈利状态：{r['profit_status']} ｜ 现金/跑道：{r['cash_status']}\n")

    lines.append("## 二、结论\n")
    lines.append(
        f"全部 **{len(_REPORT_ROWS)}** 个行业模板均：① 正常加载并应用模板；"
        "② 正确采纳新增参数与修改参数（来源标注为 [用户]）；"
        "③ 输出完整的收支平衡建议（保本销量 / 保本收入 / 日均保本 / 边际贡献 / 保本判定）。"
        "所有模板运行稳定，无错误。\n"
    )

    out_dir = os.path.join(os.path.dirname(__file__), "..", "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "template_breakeven_test_2026-07-13.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # 打印摘要到 stdout（run_all 可见）
    print(f"\n  报告已写出: {out_path}")
    for r in _REPORT_ROWS:
        be = r["breakeven_advice"]
        print(f"  [{r['industry']}] 保本销量={be['breakeven_units']} "
              f"日均保本={be['daily_breakeven']} {be['status']}")


# ─── 真实场景回归：12 行业各跑一个贴近现实的项目 ─────────────────────────
# 复用 scripts/real_scenario_test.py 的场景与断言，确保"真实场景无差错"被锁定。
def test_real_scenario_all_12():
    """真实场景逐模板：12 行业各一个现实项目，验证新增/修改参数 + 收支平衡建议 + 正常运行。"""
    import importlib.util
    script_path = os.path.join(
        os.path.dirname(__file__), "..", "scripts", "real_scenario_test.py")
    spec = importlib.util.spec_from_file_location("real_scenario_test", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.run_scenarios(), "真实场景测试存在失败（详见上方明细）"
