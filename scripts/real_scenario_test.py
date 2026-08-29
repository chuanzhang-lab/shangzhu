# -*- coding: utf-8 -*-
"""真实场景逐模板测试：12 个行业各跑一个贴近现实的项目。

验证三要素：
  (1) 修改参数 —— 覆盖模板默认值，来源须标 [用户]
  (2) 新增参数 —— 引擎支持的扩展字段被采纳并写入输出
  (3) 收支平衡建议 —— core_metrics.daily_breakeven + status.breakeven + breakeven 字典
并且：每个模板都正常运行（无 error、无 insufficient、benchmark_check 不再误报毛利率）。
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tools.workflow_engine import quick_scan

# ── 12 个真实场景（行业：贴近现实的项目描述 + 数字）────────────────────────
# modified_*  : 覆盖模板默认值的参数
# new_*       : 引擎支持的扩展字段（模板里没有）
SCENARIOS = [
    ("餐饮", "成都社区重庆小面馆", dict(
        industry="餐饮", daily_traffic=130, price_per_unit=16, monthly_rent=5500,
        total_investment=220000, employee_count=2, avg_salary=7000, variable_cost_ratio=0.42,
        city="成都", location_type="社区底商", competitor_count=6, stage="验证期",
        monthly_growth_rate=0.04, seasonal_factor=1.0, founder_count=2,
        has_financing=False)),

    ("零售", "杭州写字楼便利店", dict(
        industry="零售", daily_traffic=180, price_per_unit=28, monthly_rent=12000,
        total_investment=300000, employee_count=3, avg_salary=5500, variable_cost_ratio=0.62,
        city="杭州", location_type="写字楼底商", competitor_count=8, stage="爬坡期",
        monthly_growth_rate=0.03, seasonal_factor=0.95, founder_count=2,
        has_financing=False)),

    ("SaaS", "深圳B2B协作工具初创", dict(
        industry="SaaS", monthly_revenue=80000, monthly_rent=8000,
        total_investment=1500000, employee_count=6, avg_salary=18000, variable_cost_ratio=0.30,
        city="深圳", competitor_count=12, stage="增长期",
        monthly_growth_rate=0.08, seasonal_factor=1.0, founder_count=3,
        has_financing=True, funding_round="天使轮", funding_amount=2000000)),

    ("教育", "北京少儿编程线下小班", dict(
        industry="教育", daily_traffic=35, price_per_unit=200, monthly_rent=20000,
        total_investment=500000, employee_count=5, avg_salary=9000, variable_cost_ratio=0.35,
        city="北京", location_type="社区商业", competitor_count=10, stage="验证期",
        monthly_growth_rate=0.05, seasonal_factor=1.0, founder_count=2,
        has_financing=False)),

    ("电商", "广州服饰淘宝店", dict(
        industry="电商", daily_traffic=60, price_per_unit=89, monthly_rent=3000,
        total_investment=200000, employee_count=3, avg_salary=7500, variable_cost_ratio=0.55,
        city="广州", competitor_count=50, stage="增长期",
        monthly_growth_rate=0.06, seasonal_factor=1.1, founder_count=2,
        has_financing=False)),

    ("制造", "佛山五金小厂（薄利重资产）", dict(
        industry="制造", monthly_revenue=400000, monthly_rent=15000,
        total_investment=2000000, employee_count=12, avg_salary=6500, variable_cost_ratio=0.68,
        city="佛山", competitor_count=30, stage="规模期",
        monthly_growth_rate=0.02, seasonal_factor=1.0, founder_count=2,
        has_financing=True, funding_round="Pre-A", funding_amount=5000000)),

    ("宠物", "上海社区宠物洗护店", dict(
        industry="宠物", daily_traffic=18, price_per_unit=120, monthly_rent=10000,
        total_investment=350000, employee_count=3, avg_salary=6000, variable_cost_ratio=0.40,
        city="上海", location_type="社区底商", competitor_count=5, stage="验证期",
        monthly_growth_rate=0.05, seasonal_factor=1.0, founder_count=1,
        has_financing=False)),

    ("医疗", "成都连锁牙科诊所", dict(
        industry="医疗", daily_traffic=30, price_per_unit=600, monthly_rent=30000,
        total_investment=1500000, employee_count=10, avg_salary=12000, variable_cost_ratio=0.30,
        city="成都", location_type="商圈", competitor_count=8, stage="爬坡期",
        monthly_growth_rate=0.04, seasonal_factor=1.0, founder_count=3,
        has_financing=True, funding_round="A轮", funding_amount=8000000)),

    ("金融", "深圳量化私募小团队", dict(
        industry="金融", monthly_revenue=500000, monthly_rent=20000,
        total_investment=3000000, employee_count=8, avg_salary=25000, variable_cost_ratio=0.20,
        city="深圳", competitor_count=20, stage="增长期",
        monthly_growth_rate=0.05, seasonal_factor=1.0, founder_count=4,
        has_financing=True, funding_round="A轮", funding_amount=10000000)),

    ("内容", "杭州短视频MCN", dict(
        industry="内容", monthly_revenue=120000, monthly_rent=6000,
        total_investment=400000, employee_count=4, avg_salary=9000, variable_cost_ratio=0.25,
        city="杭州", competitor_count=40, stage="增长期",
        monthly_growth_rate=0.10, seasonal_factor=1.0, founder_count=2,
        has_financing=False)),

    ("房地产", "武汉房产分销", dict(
        industry="房地产", monthly_revenue=300000, monthly_rent=10000,
        total_investment=800000, employee_count=6, avg_salary=8000, variable_cost_ratio=0.35,
        city="武汉", competitor_count=15, stage="规模期",
        monthly_growth_rate=0.03, seasonal_factor=1.0, founder_count=2,
        has_financing=False)),

    ("企业服务", "北京SaaS咨询实施", dict(
        industry="企业服务", monthly_revenue=200000, monthly_rent=12000,
        total_investment=600000, employee_count=5, avg_salary=14000, variable_cost_ratio=0.32,
        city="北京", competitor_count=12, stage="增长期",
        monthly_growth_rate=0.06, seasonal_factor=1.0, founder_count=2,
        has_financing=True, funding_round="天使轮", funding_amount=1500000)),
]

MODIFIED_KEYS = ["employee_count", "avg_salary", "variable_cost_ratio",
                 "monthly_rent", "total_investment", "daily_traffic", "price_per_unit"]
NEW_KEYS = ["stage", "monthly_growth_rate", "founder_count", "city",
            "competitor_count", "location_type", "has_financing",
            "funding_round", "funding_amount"]


def run_scenarios():
    print("=" * 78)
    print("真实场景逐模板测试  ·  12 行业")
    print("=" * 78)
    all_ok = True
    rows = []
    for industry, desc, params in SCENARIOS:
        err = None
        try:
            raw = json.loads(quick_scan.invoke(
                {"params_json": json.dumps(params, ensure_ascii=False)}))
            # 基本运行健康
            assert "error" not in raw, f"引擎报错: {raw.get('error')}"
            assert raw.get("insufficient") is None, "参数应充分却被判 insufficient"
            assert raw.get("template_applied") is True, "模板未应用"
            # (1) 修改参数：来源标 [用户]
            src = raw.get("param_sources", {})
            for k in ("employee_count", "avg_salary", "variable_cost_ratio"):
                assert src.get(k, "").startswith("[用户]"), f"{k} 来源非[用户]: {src.get(k)}"
            # (2) 新增参数：写入输出
            outp = raw.get("params", {})
            for k in ("founder_count", "city", "competitor_count",
                      "location_type", "has_financing"):
                assert k in outp, f"新增参数 {k} 未出现在输出"
            if params.get("has_financing"):
                assert outp.get("funding_round") and outp.get("funding_amount"), \
                    "融资信息未透出"
            # 新增参数「stage」须被采纳并透出到顶层（假设清单只列非用户项，故不在此查）
            assert raw.get("stage") == params.get("stage"), \
                f"stage 未采纳/透出: {raw.get('stage')} != {params.get('stage')}"
            # (3) 收支平衡建议：unit 口径(daily_breakeven) 或 营收口径(breakeven_revenue_monthly) 至少一个成立
            cm = raw.get("core_metrics", {})
            has_be = (isinstance(cm.get("daily_breakeven"), (int, float))
                      or isinstance(cm.get("breakeven_revenue_monthly"), (int, float)))
            assert has_be, "既缺 daily_breakeven 又缺 breakeven_revenue_monthly"
            assert isinstance(raw.get("breakeven"), dict), "缺 breakeven 字典"
            assert "breakeven" in raw.get("status", {}), "status 缺 breakeven"
            # benchmark_check 不得再误报“毛利率高于行业”（已改为净利率）
            for w in raw.get("benchmark_check", []):
                assert "毛利率" not in w, f"残留毛利率误报: {w}"
            db = cm.get("daily_breakeven")
            rev_be = cm.get("breakeven_revenue_monthly")
            be_display = f"{db:.0f}/天" if isinstance(db, (int, float)) else f"月营收{rev_be:,.0f}"
            be_status = raw["status"]["breakeven"]
            nm = (cm["monthly_profit"] / cm["monthly_revenue"] * 100) if cm["monthly_revenue"] else 0
            rows.append((industry, desc, round(cm["monthly_revenue"]), round(cm["monthly_profit"]),
                         round(nm, 1), be_display, be_status,
                         len(raw.get("benchmark_check", []))))
        except Exception as e:
            all_ok = False
            rows.append((industry, desc, "-", "-", "-", "-", f"❌ {e}", 0))
            err = e
        flag = "✅" if err is None else "❌"
        print(f"{flag} {industry:<6} | {desc}")

    print("-" * 78)
    print(f"{'行业':<6}{'月营收':>10}{'月利润':>10}{'净利率':>8}{'保本建议':>16}{'判定':>14}{'基准告警':>8}")
    for r in rows:
        print(f"{r[0]:<6}{str(r[2]):>10}{str(r[3]):>10}{str(r[4]):>7}%{str(r[5]):>9}{str(r[6]):>14}{str(r[7]):>8}")

    # 打印两个典型场景的 benchmark_check，证明“真实可计算对比”有效
    print("-" * 78)
    print("benchmark_check 样例（验证不再误报、且能抓真实越界）：")
    for industry, desc, params in SCENARIOS:
        raw = json.loads(quick_scan.invoke(
            {"params_json": json.dumps(params, ensure_ascii=False)}))
        bc = raw.get("benchmark_check", [])
        tag = "⚠️ " + "；".join(bc) if bc else "✅ 符合行业常态"
        print(f"  [{industry}] {tag}")

    print("=" * 78)
    print("结论:", "全部 12 模板真实场景通过，无差错 ✅" if all_ok else "存在失败 ❌")
    print("=" * 78)
    return all_ok


if __name__ == "__main__":
    sys.exit(0 if run_scenarios() else 1)
