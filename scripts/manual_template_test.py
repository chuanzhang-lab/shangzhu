"""手动逐一实跑 12 个行业模板：新增参数 + 修改参数 + 收支平衡建议 + 运行确认。

与自动化测试不同，这里逐个调用 quick_scan 并打印【真实引擎输出】，
并对每个模板单独 try/except，确保任一出错都能精确定位、不掩盖。
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tools.workflow_engine import INDUSTRY_TEMPLATES, quick_scan


def build_case(industry, tpl):
    if tpl["variable_cost_ratio"] > 0.3:
        mod_vc = round(tpl["variable_cost_ratio"] - 0.05, 2)
    else:
        mod_vc = round(tpl["variable_cost_ratio"] + 0.05, 2)
    mod_salary = int(tpl["avg_salary"] * 1.1)
    mod_staff = tpl["employee_count"] + 1
    return {
        "industry": industry,
        # 修改参数（覆盖模板默认）
        "employee_count": mod_staff,
        "avg_salary": mod_salary,
        "variable_cost_ratio": mod_vc,
        # 新增参数（模板不含）
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


def main():
    print("=" * 72)
    print("手动逐一实跑 · 12 行业模板测试（新增参数 / 修改参数 / 收支平衡建议）")
    print("=" * 72)

    ok = 0
    fail = 0
    for i, industry in enumerate(INDUSTRY_TEMPLATES.keys(), 1):
        tpl = INDUSTRY_TEMPLATES[industry]
        params = build_case(industry, tpl)
        print(f"\n{'─'*72}")
        print(f"[{i:02d}/12] 行业模板：{industry}")
        print(f"{'─'*72}")
        try:
            raw = json.loads(quick_scan.invoke({"params_json": json.dumps(params, ensure_ascii=False)}))

            # 1) 运行确认
            assert "error" not in raw, f"引擎返回 error: {raw.get('error')}"
            assert raw.get("template_applied") is True, "模板未应用"
            assert raw.get("insufficient") is not True, "被误判不充分"

            # 2) 修改参数生效（来源=[用户]）
            src = raw.get("param_sources", {})
            assert src.get("employee_count", "").startswith("[用户]")
            assert src.get("avg_salary", "").startswith("[用户]")
            assert src.get("variable_cost_ratio", "").startswith("[用户]")

            # 3) 新增参数被采纳
            out = raw.get("params", {})
            assert out.get("city") == "上海", "city 未写入"
            assert out.get("founder_count") == 2, "founder_count 未写入"

            # 4) 收支平衡建议
            be = raw.get("breakeven", {})
            assert isinstance(be, dict) and "error" not in be
            assert be.get("breakeven_units", 0) > 0
            core = raw.get("core_metrics", {})
            assert "daily_breakeven" in core
            status = raw.get("status", {})
            assert status.get("breakeven")

            print(f"  ✅ 运行正常 | 模板模式：{raw.get('template_mode','')}")
            print(f"  ✏️ 修改参数（模板默认 → 测试值，来源[用户]）：")
            print(f"      employee_count : {tpl['employee_count']} → {params['employee_count']}")
            print(f"      avg_salary     : {tpl['avg_salary']} → {params['avg_salary']}")
            print(f"      variable_cost  : {tpl['variable_cost_ratio']} → {params['variable_cost_ratio']}")
            print(f"  🆕 新增参数（已采纳）：daily_traffic={params['daily_traffic']} "
                  f"price={params['price_per_unit']} invest={params['total_investment']} "
                  f"rent={params['monthly_rent']} 融资={params['funding_round']}{params['funding_amount']} "
                  f"创始人={params['founder_count']} 城市={out.get('city')} 竞品={params['competitor_count']}")
            print(f"  ⚖️ 收支平衡建议：")
            print(f"      保本销量   : {be.get('breakeven_units')} 单位/年")
            print(f"      保本收入   : ¥{be.get('breakeven_revenue'):,}")
            print(f"      日均保本   : {core.get('daily_breakeven')} 单位/天")
            print(f"      边际贡献   : ¥{be.get('contribution_margin_per_unit')} / 单位")
            print(f"      保本判定   : {status.get('breakeven')}")
            print(f"      盈利/现金  : {status.get('profit')} ｜ {status.get('cash')}")
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  ❌ 失败：{type(e).__name__}: {e}")

    print("\n" + "=" * 72)
    print(f"实跑完成：{ok} 个模板正常，{fail} 个失败（共 {ok+fail} 个）")
    print("=" * 72)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
