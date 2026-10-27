"""M-06 静态守卫（2026-10）：改参切结构化 + 模板预填的 app.js 契约。

口径同 test_form_render_static.py：DOM/网络行为归 e2e 管，这里锁
「NL 合成已删 / F4 补丁已删 / pcRecalc 改调 PUT / F3 NL 链已删 /
高亮保留 / 行业预填已接线」六条静态事实。红先行：先于实现落盘。
"""
from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "src" / "web_static" / "app.js"


def _app_js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _pc_recalc_handler(src: str) -> str:
    m = re.search(r"pcRecalc\.addEventListener\('click',[\s\S]*?\n\}\);", src)
    assert m, "pcRecalc click 处理器不存在（改参入口被删了？）"
    return m.group(0)


def test_无nl合成改为句式() -> None:
    """pcRecalc/Enter 不许再把结构化值合成 NL 句子（'改为' 是合成句式的痕迹）。
    round-trip（结构化→文本→再解析）是 P-04 本体，M-06 后必须零出现。"""
    assert "'改为'" not in _app_js(), "app.js 仍有 NL 合成句式 '改为'——P-04 未关闭"


def test_无f4补丁origshown() -> None:
    """F4 补丁的 % 比对 quirk（origShown）随 NL 合成一并删除，
    改动检测走 saveParamsForm 同款 formInputValue 口径。"""
    assert "origShown" not in _app_js(), "F4 补丁 origShown 仍在——应随 NL 合成删除"


# 注：原 test_pcrecalc改调put（pcRecalc 处理器改调 submitParams）随 M-08
# 计划性删除旧改参区而退役（计划 6.10「保留一版，M-06 后删」）；
# 「PUT 唯一真源」不变量由 test_m08_static.test_put唯一写入口 承接。


def test_f3_nl采纳链已删() -> None:
    """F3 采纳校验链（pendingParamChange + validateParamAdoption）只服务 NL 合成路径，
    M-06 后无喂食者，必须整体删除而非留死码。"""
    src = _app_js()
    assert "pendingParamChange" not in src, "F3 pendingParamChange 死码仍在"
    assert "validateParamAdoption" not in src, "F3 validateParamAdoption 死码仍在"


def test_f3高亮迁至结构化路径() -> None:
    """F3 面板高亮保留（M-05 决策），但 setter 迁到结构化保存路径，
    不许连高亮一起删。"""
    src = _app_js()
    assert "recentlyUpdatedField" in src, "F3 高亮 recentlyUpdatedField 被误删"
    # ^\s* 锚定行首：排除 `let recentlyUpdatedField = null` 声明行，
    # 只有真实赋值语句（迁移后的结构化保存路径）才满足。
    assert re.search(r"^\s*recentlyUpdatedField\s*=", src, re.M), (
        "recentlyUpdatedField 只剩消费无 setter——高亮永不触发"
    )


def test_行业预填已接线() -> None:
    """模板预填四件套：行业选择器（读 schema.templates）+ [默认] 标 +
    benchmark 参考列 + 「重置为模板默认」。"""
    src = _app_js()
    assert re.search(r"\.templates", src), "前端未读 schema.templates——预填无数据源"
    assert "pf-industry" in src, "行业选择器（#pf-industry）未接线"
    assert "重置为模板默认" in src, "「重置为模板默认」按钮缺失"
    assert "psrc-default" in src, "[默认] 来源标缺失"
    assert "pf-bench" in src, "benchmark 参考列缺失"