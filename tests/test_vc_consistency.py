"""F1 回归测试：变动成本率采纳一致性（2026-08-19）。

覆盖三个真实缺陷的修复：
1. 抽取层：『变动成本改为60%』（不带率字）也能产出归一化 variable_cost_ratio，
   不再只有 variable_cost_rate（缺陷：改参不生效）。
2. merge 层：新输入只带 variable_cost_rate 时，同步补齐 variable_cost_ratio，
   避免引擎（优先消费 ratio）拿到旧值。
3. 引擎消费：T1(40%) 合并 T2(改为60%) 后，quick_scan 结果用 60% 计算。
4. 不误抓：『每份成本45元』（单位成本）不产出 ratio；『日售50杯变动成本率55%』正确去噪。
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from router.param_extractor import extract_params
from session_state import merge_params
from tools.workflow_engine import quick_scan


def test_extract_vc_without_rate_word_gives_ratio():
    """『变动成本改为60%』不带『率』字，也应产出归一化 ratio=0.6。"""
    d = extract_params("把变动成本改为60%，你再算下它的盈亏")
    assert d.get("variable_cost_ratio") == 0.6
    # 精确 ratio 已抽出时，通用 rate 去噪丢弃，避免双字段污染引擎
    assert d.get("variable_cost_rate") is None


def test_extract_vc_variants_all_normalized():
    """多种措辞都归一化到 0~1：成本率40%、可变成本率30%、食材成本占45%。"""
    assert extract_params("成本率40%").get("variable_cost_ratio") == 0.4
    assert extract_params("可变成本率30%").get("variable_cost_ratio") == 0.3
    assert extract_params("食材成本占营业额45%").get("variable_cost_ratio") == 0.45


def test_not_misgrab_unit_cost():
    """『每份成本45元』是单位变动成本，不应误抓成 ratio。"""
    d = extract_params("每份成本45元")
    assert d.get("variable_cost_ratio") is None


def test_extract_vc_noise_denoised():
    """『日售50杯变动成本率55%』：rate 误抓客流 50，应被去噪只留精确 ratio=0.55。"""
    d = extract_params("日售50杯变动成本率55%")
    assert d.get("variable_cost_ratio") == 0.55
    assert d.get("variable_cost_rate") is None


def test_merge_syncs_ratio_from_rate():
    """merge：新输入只带 rate 时，补齐 ratio=rate/100（防引擎拿旧值）。"""
    old = {"variable_cost_ratio": 0.4, "variable_cost_rate": 40.0}
    new = {"variable_cost_rate": 60.0}  # 模拟只抽到 rate 的极端路径
    merged = merge_params(old, new)
    assert merged["variable_cost_rate"] == 60.0
    assert merged["variable_cost_ratio"] == 0.6


def test_full_pipeline_vc_updated_to_60():
    """T1(40%) 合并 T2(改为60%) → quick_scan 用 60% 算（缺陷 1 主证据）。"""
    t1 = extract_params("我开咖啡店，月租金15000，日均客流50，客单价25，员工3人，人均工资5000，变动成本率40%")
    t2 = extract_params("把变动成本改为60%，你再算下它的盈亏")
    merged = merge_params(t1, t2)
    assert merged.get("variable_cost_ratio") == 0.6
    qr = json.loads(quick_scan.invoke({"params_json": json.dumps(merged, ensure_ascii=False)}))
    # 引擎按 60% 计算：rev=37500, fixed=30000, profit=37500-30000-37500*0.6=-15000
    profit = (qr.get("core_metrics") or {}).get("monthly_profit")
    assert profit is not None
    assert round(profit, 0) == -15000.0, f"期望按 60% 算得 -15000，实际 {profit}"
    assert profit != -7500  # 关键：不再是 40% 时的旧结果


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
