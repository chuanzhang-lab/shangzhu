"""统一测试运行器（无需 pytest）——**后备门禁**。

⚠️ 交付门禁是 `make test`（= `pytest tests/` 全量收集）。
   本脚本只在没有 pytest 的环境下作轻量后备使用。

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

    覆盖度限制（重要）：带 `client` / `monkeypatch` 等 **pytest fixture 形参** 的用例，
    本运行器无法注入，会显式标记为 `SKIP`（单列计数、不并入 passed），
    因此本脚本的通过数**少于** pytest 全量。交付门禁请用 `make test`。

各测试文件本身也可单独运行 / 被 pytest 收集。
"""
import inspect
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
import test_config_priority as t21
import test_direction_2_4 as t22
import test_direction_5_1 as t23
import test_concurrency_fixes as t24
# 以下 8 个曾游离在门禁之外（新增功能因此没有回归保护），现已全部注册
import test_advisor_endpoints as t25
import test_advisor_formatter as t26
import test_cors_config as t27
import test_cost_attribution as t28
import test_industry_seasonal as t29
import test_llm_settings as t30
import test_simulator_upgrade as t31
import test_vc_consistency as t32


def _bind(cls, fn):
    """把类方法绑定到实例；需要 pytest fixture 的用例返回 None（由调用方记为 SKIP）。

    修复两个历史缺陷：
    1. 原实现只用 vars(mod) 扫模块级函数，`class TestXxx` 里的用例
       （advisor / llm_settings / simulator_upgrade 等）永远收集不到
       —— 这正是「25/33 个文件、270 passed」假绿灯的根因。
    2. 若把类方法一律直接调用，带 `client` / `monkeypatch` 形参的用例会抛
       TypeError 变成「假红」。这类用例必须交给 pytest，故此处显式识别并跳过。
    """
    extra = [p for p in inspect.signature(fn).parameters.values() if p.name != "self"]
    if extra:
        return None

    def runner():
        inst = cls()
        return fn(inst)
    return runner


def _collect(mod):
    """收集模块内全部用例：模块级 test_* 函数 + class Test* 内的 test_* 方法。"""
    items = []
    for name, obj in vars(mod).items():
        if name.startswith("test_") and callable(obj):
            items.append((name, obj))
        elif isinstance(obj, type) and name.startswith("Test"):
            for mname, mfn in vars(obj).items():
                if mname.startswith("test_") and callable(mfn):
                    items.append((f"{name}::{mname}", _bind(obj, mfn)))
    return sorted(items, key=lambda kv: kv[0])


def _run_module(mod, label):
    funcs = _collect(mod)
    passed = failed = skipped = 0
    print(f"\n── {label}（{len(funcs)} 用例）──")
    for name, fn in funcs:
        if fn is None:
            print(f"  SKIP {name}  ← 需 pytest fixture，本运行器无法注入")
            skipped += 1
            continue
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
    return passed, failed, skipped


if __name__ == "__main__":
    total_p = total_f = total_s = 0
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
        (t21, "ConfigPriority · 配置优先级"),
        (t22, "Direction2_4 · 方向2.4/2.5"),
        (t23, "Direction5_1 · 方向5.1"),
        (t24, "Concurrency · 并发安全修复守护"),
        (t25, "AdvisorEndpoints · 顾问端点（类方法风格）"),
        (t26, "AdvisorFormatter · 顾问格式化（类方法风格）"),
        (t27, "CorsConfig · CORS 白名单 + POST 防 CSRF"),
        (t28, "CostAttribution · 成本归因 + 敏感性（类方法风格）"),
        (t29, "IndustrySeasonal · 行业季节性模板（类方法风格）"),
        (t30, "LlmSettings · LLM 配置读写（类方法风格）"),
        (t31, "SimulatorUpgrade · 收入序列 / 投资指标（类方法风格）"),
        (t32, "VcConsistency · 变动成本率一致性"),
    ):
        p, f, s = _run_module(mod, label)
        total_p += p
        total_f += f
        total_s += s
    print(f"\n==== 总计: {total_p} passed, {total_f} failed, {total_s} skipped ====")
    if total_s:
        print(f"⚠️  有 {total_s} 个用例需 pytest fixture，本后备运行器无法执行（已显式跳过，未计入通过）。")
        print("   交付门禁请使用：make test   （= pytest tests/ 全量收集）")
    sys.exit(1 if total_f else 0)
