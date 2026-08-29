"""验证模板中等增强是否真正生效。"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from tools.workflow_engine import quick_scan, INDUSTRY_TEMPLATES

def scan(d):
    # d 为 dict，内部只编码一次
    return json.loads(quick_scan.invoke({"params_json": json.dumps(d, ensure_ascii=False)}))

print("=== 验证1：gross_margin 死代码已清除（模板不再含该字段）===")
assert all("gross_margin" not in t for t in INDUSTRY_TEMPLATES.values()), "模板仍含 gross_margin"
print("  ✅ 12 个模板均已不含 gross_margin，毛利率改为由 variable_cost_ratio 推导")

print("\n=== 验证2：benchmark_check 真实超界告警 ===")
# 餐饮：毛利率设为 90%（variable_cost_ratio=0.10）→ 高于行业 15-25%
d = scan({"industry": "餐饮", "variable_cost_ratio": 0.10,
                     "daily_traffic": 120, "price_per_unit": 35,
                     "total_investment": 300000, "monthly_rent": 12000})
bc = d["benchmark_check"]
print(f"  毛利率 90% → benchmark_check: {bc}")
assert any("高于行业典型" in w for w in bc), "未抓出毛利率过高"
# 餐饮：毛利率设为 5%（variable_cost_ratio=0.95）→ 低于行业 15-25%
d2 = scan({"industry": "餐饮", "variable_cost_ratio": 0.95,
                      "daily_traffic": 120, "price_per_unit": 35,
                      "total_investment": 300000, "monthly_rent": 12000})
bc2 = d2["benchmark_check"]
print(f"  毛利率 5% → benchmark_check: {bc2}")
assert any("低于行业典型" in w for w in bc2), "未抓出毛利率过低"
# 餐饮：日均客流 30（<80 行业下限）→ 客流告警
d3 = scan({"industry": "餐饮", "variable_cost_ratio": 0.40,
                      "daily_traffic": 30, "price_per_unit": 35,
                      "total_investment": 300000, "monthly_rent": 12000})
bc3 = d3["benchmark_check"]
print(f"  日均客流 30 → benchmark_check: {bc3}")
assert any("日均客流" in w for w in bc3), "未抓出客流不足"
print("  ✅ benchmark 超界对比真实生效（毛利率/客流）")

print("\n=== 验证3：cost_structure 行业成本结构已输出 ===")
d = scan({"industry": "餐饮", "daily_traffic": 120, "price_per_unit": 35,
                     "total_investment": 300000, "monthly_rent": 12000})
cs = d.get("industry_cost_structure")
print(f"  餐饮 cost_structure: {cs}")
assert cs and abs(sum(cs.values()) - 1.0) < 1e-6, "成本结构占比未归一"
print("  ✅ 行业成本结构占比已输出且归一")

print("\n=== 验证4：劳动负担率对用户显式人工生效；未给人工不虚构 ===")
print("\n=== 验证4：劳动负担率对用户显式人工生效；未给人工不虚构 ===")
# 用户显式给 3人×7000 → 真实成本含 40% 雇主负担 → 人工=29400，固定=12000+29400=41400
du = scan({"industry": "餐饮", "employee_count": 3, "avg_salary": 7000,
                      "daily_traffic": 120, "price_per_unit": 35,
                      "total_investment": 300000, "monthly_rent": 12000})
print(f"  用户给 3人×7000 → 含社保负担后人工=29400，固定成本含此")
assert abs(du["params"]["monthly_fixed_cost"] - (12000 + 29400)) < 1, f"{du['params']['monthly_fixed_cost']}"
# 仅给行业、不给人 → 保守原则：不虚构人工，固定成本仅含租金=12000
dt = scan({"industry": "餐饮", "daily_traffic": 120, "price_per_unit": 35,
                      "total_investment": 300000, "monthly_rent": 12000})
print(f"  仅行业(未给人) → 不虚构人工，固定成本=12000")
assert abs(dt["params"]["monthly_fixed_cost"] - 12000) < 1, f"{dt['params']['monthly_fixed_cost']}"
print("  ✅ 用户人工真实叠加社保负担(×1.4)；未提供人工时不虚构")

print("\n全部增强验证通过 ✅")
