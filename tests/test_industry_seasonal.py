"""行业季节模板测试 — 覆盖季节系数读取与趋势渲染。

测试模块：
- C1: 餐饮季节系数正确读取
- C2: 零售季节系数正确读取
- C3: 电商季节系数正确读取
- C4: 无行业 → fallback 通用 map
- C5: 趋势预测中季节系数生效
- C6: seasonal_source 标注
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tools.workflow_engine import (
    _get_industry_seasonal_profile,
    _DEFAULT_SEASON_MAP,
    _project_trend_12m,
)


# ─── C1-C3: 行业季节系数读取 ──────────────────────────────────────────────

class TestIndustrySeasonalProfile:
    """行业季节系数从 YAML 模板读取。"""

    def test_restaurant_seasonal(self):
        """餐饮：1月（春节）应高于基准。"""
        profile = _get_industry_seasonal_profile("餐饮")
        assert len(profile) == 12
        assert profile[1] == 1.2  # 1月春节旺
        assert profile[7] == 1.15  # 7月饮品旺
        assert profile[3] == 0.9  # 3月淡季

    def test_retail_seasonal(self):
        """零售：11月（双11）应为全年最高。"""
        profile = _get_industry_seasonal_profile("零售")
        assert len(profile) == 12
        assert profile[11] == 1.3  # 双11
        assert profile[2] == 0.8  # 2月淡季

    def test_ecommerce_seasonal(self):
        """电商：6月（618）和11月（双11）应为高峰。"""
        profile = _get_industry_seasonal_profile("电商")
        assert len(profile) == 12
        assert profile[6] == 1.3  # 618
        assert profile[11] == 1.5  # 双11
        assert profile[3] == 0.85  # 3月淡季

    def test_alias_resolution(self):
        """别名解析：cafe → 餐饮。"""
        profile = _get_industry_seasonal_profile("cafe")
        assert profile[1] == 1.2  # 同餐饮

    def test_unknown_industry_fallback(self):
        """未知行业 → 通用 map。"""
        profile = _get_industry_seasonal_profile("未知行业")
        assert profile == _DEFAULT_SEASON_MAP

    def test_empty_industry_fallback(self):
        """空行业名 → 通用 map。"""
        profile = _get_industry_seasonal_profile("")
        assert profile == _DEFAULT_SEASON_MAP


# ─── C5: 趋势预测中季节系数生效 ────────────────────────────────────────────

class TestTrendWithSeasonal:
    """趋势预测中行业季节系数正确应用。"""

    def test_restaurant_jan_higher_than_mar(self):
        """餐饮：1月（春节旺）营收应高于3月（淡季）。"""
        params = {
            "monthly_revenue": 30000,
            "monthly_fixed_cost": 15000,
            "variable_cost_ratio": 0.4,
            "available_cash": 100000,
            "total_investment": 100000,
            "industry_name": "餐饮",
        }
        result = _project_trend_12m(params)
        jan_revenue = result["months"][0]["revenue"]  # 1月
        mar_revenue = result["months"][2]["revenue"]  # 3月
        # 1月系数 1.2, 3月系数 0.9
        assert jan_revenue > mar_revenue

    def test_ecommerce_nov_peak(self):
        """电商：11月营收应为全年最高。"""
        params = {
            "monthly_revenue": 30000,
            "monthly_fixed_cost": 15000,
            "variable_cost_ratio": 0.6,
            "available_cash": 100000,
            "total_investment": 100000,
            "industry_name": "电商",
        }
        result = _project_trend_12m(params)
        revenues = [m["revenue"] for m in result["months"]]
        # 11月（index 10）应为最高
        assert revenues[10] == max(revenues)

    def test_seasonal_source_annotation(self):
        """有行业模板时，seasonal_source 标注行业名。"""
        params = {
            "monthly_revenue": 30000,
            "monthly_fixed_cost": 15000,
            "variable_cost_ratio": 0.4,
            "available_cash": 100000,
            "total_investment": 100000,
            "industry_name": "餐饮",
        }
        result = _project_trend_12m(params)
        assert "餐饮" in result.get("seasonal_source", "")

    def test_generic_seasonal_source(self):
        """无行业时，seasonal_source 标注通用。"""
        params = {
            "monthly_revenue": 30000,
            "monthly_fixed_cost": 15000,
            "variable_cost_ratio": 0.4,
            "available_cash": 100000,
            "total_investment": 100000,
            "industry_name": "",
        }
        result = _project_trend_12m(params)
        assert "通用" in result.get("seasonal_source", "")


# ─── 运行 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
