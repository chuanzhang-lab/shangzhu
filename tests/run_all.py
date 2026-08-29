"""统一测试运行器（无需 pytest）。

运行：
    .venv/bin/python3 tests/run_all.py

测试范围（明确边界）：
    本套测试只覆盖【本地独立工作台 = 引擎层(A)】——
    即 router(参数抽取/意图) → session_state(跨轮merge) → workflow_engine(quick_scan)
    → financial_calculator → formatter → llm_advisor(Engine Steward) 全链路，
    以及 12 轮羊肉汤店对话集成 oracle。
    另含本地存储层（local_store 内存/PG store）与任务 CRUD API（test_local_store /
    test_task_api）。

    不覆盖【Coze 平台服务(B) = src/main.py + agents 栈 + storage/s3 + 报告/调研工具】——
    该路径由平台侧保障、依赖平台运行时(重型栈)，本仓不交付也不测。
    相关解耦由 test_phase4_workbench.test_p48_* 硬性守护（web_server 不得 import agents.agent）。

    Cleanup 测试（test_cleanup）是例外：仅做技术债清理的回归守护（如
    project_manager 解析器去重），用隔离子进程 stub langchain.tools 验证，
    不依赖平台运行时，不覆盖 B 路径的 agent 编排 / 存储 / 平台服务。

各测试文件本身也可单独运行 / 被 pytest 收集。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import test_quick_scan_phase0 as t0
import test_phase1_flexibility as t1
import test_phase2_llm_advisor as t2
import test_phase3_session_alignment as t3
import test_phase4_workbench as t4
import test_cleanup as t5
import test_param_extractor_fixes as t6
import test_financial_calculator as t7
import test_formatter as t8
import test_web_server_robustness as t9
import test_template_breakeven as t10
import test_param_guard as t11
import test_real_dialogs as t12
import test_local_store as t13
import test_task_api as t14
import test_hypothesis_layer as t15
import test_decision_engine as t16
import test_cashflow as t17
import test_derived as t18
import test_consistency as t19
import test_field_model as t20


def _run_module(mod, label):
    funcs = sorted(
        (n, f) for n, f in vars(mod).items()
        if n.startswith("test_") and callable(f)
    )
    passed = failed = 0
    print(f"\n── {label}（{len(funcs)} 用例）──")
    for name, fn in funcs:
        try:
            fn()
            print(f"  PASS {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {name}: {e}")
            failed += 1
        except Exception as e:  # noqa
            print(f"  ERROR {name}: {e!r}")
            failed += 1
    return passed, failed


if __name__ == "__main__":
    total_p = total_f = 0
    for mod, label in (
        (t0, "Phase 0 · 置信层 + 门禁"),
        (t1, "Phase 1 · 灵活度层"),
        (t2, "Phase 2 · LLM 协作层"),
        (t3, "Phase 3 · 跨轮对齐层"),
        (t4, "Phase 4 · 工作台一体化"),
        (t5, "Cleanup · 卫生项收敛"),
        (t6, "ParamExtractor · 缺陷修复守护"),
        (t7, "FinancialCalculator · 财务引擎单测"),
        (t8, "Formatter · 模板格式化单测"),
        (t9, "WebServer · 健壮性边界"),
        (t10, "TemplateBreakeven · 12 行业模板覆盖"),
        (t11, "ParamGuard · 参数守门层"),
        (t12, "RealDialogs · 真实对话 oracle"),
        (t13, "LocalStore · 本地存储层"),
        (t14, "TaskAPI · 任务 CRUD 端点"),
        (t15, "HypothesisLayer · 数据基础层（取消输入默认）"),
        (t16, "DecisionEngine · L2 决策引擎"),
        (t17, "Cashflow · 现金流明细（档 B）"),
        (t18, "Derived · 精确推算层"),
        (t19, "Consistency · 数据一致性（派生一致性）"),
        (t20, "FieldModel · 声明式字段模型"),
    ):
        p, f = _run_module(mod, label)
        total_p += p
        total_f += f
    print(f"\n==== 总计: {total_p} passed, {total_f} failed ====")
    sys.exit(1 if total_f else 0)
