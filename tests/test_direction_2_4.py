"""验证 Direction 2（改主意权）+ Direction 4（版本号）改动。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from session_state import apply_turn_guarded, reset_state, to_llm_view
from param_guard import _values_conflict


# ── Direction 2：上下文感知矛盾阈值 ──────────────────────────────────────

def test_d2_continuation_relaxed_threshold():
    """is_continuation=True 时，大幅变更不判矛盾（用户主动改参）。"""
    # 租金从 8000 改到 16000（ratio=1.0，100% 变化）
    # 非续算：ratio > 10x 才判 → 1.0 < 10 → 不矛盾（原逻辑也通过）
    assert _values_conflict("monthly_rent", 8000, 16000, is_continuation=False) is False
    # 续算：ratio > 100x 才判 → 1.0 < 100 → 不矛盾
    assert _values_conflict("monthly_rent", 8000, 16000, is_continuation=True) is False
    print("PASS test_d2_continuation_relaxed_threshold")


def test_d2_non_continuation_strict_threshold():
    """is_continuation=False 时，大幅变更判矛盾（可能是笔误）。"""
    # 租金从 8000 改到 800000（ratio=99，>10x）
    assert _values_conflict("monthly_rent", 8000, 800000, is_continuation=False) is True
    # 续算时：ratio=99 < 100x → 不矛盾（用户说「改成」，接受大变更）
    assert _values_conflict("monthly_rent", 8000, 800000, is_continuation=True) is False
    print("PASS test_d2_non_continuation_strict_threshold")


def test_d2_ratio_field_threshold():
    """比例类字段的续算/非续算阈值差异。"""
    # variable_cost_ratio 从 0.5 改到 0.8（ratio=0.6，60% 变化）
    # 非续算：ratio > 0.5 → True（判矛盾）
    assert _values_conflict("variable_cost_ratio", 0.5, 0.8, is_continuation=False) is True
    # 续算：ratio > 2.0 → False（不判矛盾，用户主动调整）
    assert _values_conflict("variable_cost_ratio", 0.5, 0.8, is_continuation=True) is False
    print("PASS test_d2_ratio_field_threshold")


def test_d2_extreme_change_still_caught():
    """即使是续算，极端变更仍判矛盾（如 0.5→1.5 不可能合法）。"""
    assert _values_conflict("variable_cost_ratio", 0.5, 1.5, is_continuation=True) is True
    print("PASS test_d2_extreme_change_still_caught")


def test_d2_integration_continuation_in_apply():
    """集成测试：用户说「租金改成16000」不弹矛盾确认。"""
    tid = "test-d2-integration"
    reset_state(tid)
    # 第 1 轮：给租金 8000
    apply_turn_guarded(tid, {"monthly_rent": 8000}, "月租8000")
    # 第 2 轮：用户说「租金改成16000」（续算意图 + 大幅变更）
    st, guard = apply_turn_guarded(tid, {"monthly_rent": 16000}, "租金改成16000")
    # 不应有矛盾（续算时放宽阈值）
    contradictions = guard.get("contradictions", [])
    rent_contradictions = [c for c in contradictions if c.get("field") == "monthly_rent"]
    assert len(rent_contradictions) == 0, f"续算时不应判矛盾: {rent_contradictions}"
    # 值应已更新
    assert st["params"]["monthly_rent"] == 16000
    print("PASS test_d2_integration_continuation_in_apply")


# ── Direction 4：版本号 ──────────────────────────────────────────────────

def test_d4_version_increments():
    """每次 apply_turn_guarded 版本号 +1。"""
    tid = "test-d4-version"
    reset_state(tid)
    view0 = to_llm_view(tid)
    assert view0["version"] == 0
    apply_turn_guarded(tid, {"monthly_rent": 8000}, "月租8000")
    view1 = to_llm_view(tid)
    assert view1["version"] == 1
    apply_turn_guarded(tid, {"daily_traffic": 60}, "日均60杯")
    view2 = to_llm_view(tid)
    assert view2["version"] == 2
    print("PASS test_d4_version_increments")


def test_d4_version_in_view():
    """version 字段在 to_llm_view 输出中。"""
    tid = "test-d4-view"
    reset_state(tid)
    apply_turn_guarded(tid, {"monthly_rent": 8000}, "")
    view = to_llm_view(tid)
    assert "version" in view
    assert isinstance(view["version"], int)
    assert view["version"] >= 1
    print("PASS test_d4_version_in_view")


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
