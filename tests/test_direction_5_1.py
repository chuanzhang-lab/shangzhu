"""验证 Direction 1+5 合并改动：参数分组 + 注意力过滤 + hypotheses 进视图。"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from session_state import (
    apply_turn_guarded, reset_state, to_llm_view,
    infer_focus_fields, record_accepted_hypothesis, PARAM_GROUPS
)


def test_grouped_params():
    """Direction 1: to_llm_view 按语义分组输出参数。"""
    tid = "test-grouped"
    reset_state(tid)
    apply_turn_guarded(tid, {"industry": "餐饮", "total_investment": 200000,
                             "monthly_rent": 8000, "daily_traffic": 60,
                             "price_per_unit": 15, "employee_count": 2,
                             "avg_salary": 3000, "variable_cost_ratio": 0.55},
                       "", "餐饮")
    view = to_llm_view(tid)
    grouped = view["grouped_params"]
    # 收入模型分组应含 daily_traffic, price_per_unit
    assert "收入模型" in grouped, f"缺少收入模型分组: {grouped.keys()}"
    assert "daily_traffic" in grouped["收入模型"]
    assert "price_per_unit" in grouped["收入模型"]
    # 成本结构分组应含 monthly_rent, employee_count, avg_salary, variable_cost_ratio
    assert "成本结构" in grouped
    assert "monthly_rent" in grouped["成本结构"]
    assert "employee_count" in grouped["成本结构"]
    # 投资与跑道分组
    assert "投资与跑道" in grouped
    assert "total_investment" in grouped["投资与跑道"]
    # 行业与定位
    assert "行业与定位" in grouped
    assert "industry" in grouped["行业与定位"]
    print("PASS test_grouped_params")


def test_focus_filtering():
    """Direction 5: focus_fields 过滤后只保留相关参数 + 核心派生参数。"""
    tid = "test-focus"
    reset_state(tid)
    apply_turn_guarded(tid, {"industry": "餐饮", "total_investment": 200000,
                             "monthly_rent": 8000, "daily_traffic": 60,
                             "price_per_unit": 15, "employee_count": 2,
                               "avg_salary": 3000, "variable_cost_ratio": 0.55},
                       "", "餐饮")
    # 全量视图
    full = to_llm_view(tid)
    full_count = len(full["params"])
    # 关注「客流」
    focus = infer_focus_fields("日均客流能到多少")
    assert focus is not None
    assert "daily_traffic" in focus
    focused = to_llm_view(tid, focus_fields=focus)
    # 过滤后参数应少于全量
    assert len(focused["params"]) < full_count, (
        f"过滤后 {len(focused['params'])} 应少于全量 {full_count}"
    )
    # daily_traffic 必须在过滤结果里
    assert "daily_traffic" in focused["params"]
    # params_summary 应包含被过滤掉的字段
    assert "params_summary" in focused
    if focused["params_summary"]:
        assert "monthly_rent" in focused["params_summary"] or "employee_count" in focused["params_summary"]
    print("PASS test_focus_filtering")


def test_infer_focus_fields():
    """infer_focus_fields 从文本推断关注字段。"""
    assert infer_focus_fields("日均客流能到多少") is not None
    assert "daily_traffic" in infer_focus_fields("日均客流能到多少")
    assert infer_focus_fields("租金太高了") is not None
    assert "monthly_rent" in infer_focus_fields("租金太高了")
    assert infer_focus_fields("人工改成3个人") is not None
    assert infer_focus_fields("今天天气怎么样") is None  # 无关话题 → None
    assert infer_focus_fields("") is None
    print("PASS test_infer_focus_fields")


def test_accepted_hypotheses_in_view():
    """Direction 3: accepted_hypotheses 进入 to_llm_view。"""
    tid = "test-hyp-view"
    reset_state(tid)
    apply_turn_guarded(tid, {"industry": "餐饮"}, "", "餐饮")
    record_accepted_hypothesis(tid, "avg_salary", 3000, "餐饮")
    view = to_llm_view(tid)
    assert "accepted_hypotheses" in view
    assert view["accepted_hypotheses"].get("avg_salary") == {"value": 3000, "industry": "餐饮"}
    print("PASS test_accepted_hypotheses_in_view")


def test_backward_compat_no_focus():
    """向后兼容：不传 focus_fields 时行为与旧版一致。"""
    tid = "test-compat"
    reset_state(tid)
    apply_turn_guarded(tid, {"monthly_rent": 8000, "daily_traffic": 60}, "")
    view = to_llm_view(tid)
    # 旧字段都在
    assert "params" in view
    assert "industry" in view
    assert "turn" in view
    assert "last_changes" in view
    # 新字段也在（不破坏旧消费者）
    assert "grouped_params" in view
    assert "accepted_hypotheses" in view
    assert "params_summary" in view
    # params_summary 无 focus 时为空
    assert view["params_summary"] == ""
    print("PASS test_backward_compat_no_focus")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {t.__name__}: {e}")
            failed += 1
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)
