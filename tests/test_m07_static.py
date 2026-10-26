"""M-07 静态守卫（2026-10）：NL 确认层前后端接线契约。

口径同 test_m06_static.py：运行行为归 e2e/契约测试管，这里锁静态事实——
后端字段与拦截分支、前端请求/响应接线、确认条三件套（确认开算/忽略/
跳过开关）、待确认来源标。红先行：先于实现落盘。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "src" / "web_static" / "app.js"
WEB_SERVER = ROOT / "web_server.py"


def _app_js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _web_server() -> str:
    return WEB_SERVER.read_text(encoding="utf-8")


def test_chatrequest_有nl_confirm字段() -> None:
    """后端显式 opt-in：ChatRequest 声明 nl_confirm（None=未声明走旧路径）。"""
    src = _web_server()
    m = re.search(r"class ChatRequest\(BaseModel\):[\s\S]*?\n\n", src)
    assert m, "ChatRequest 不见了"
    assert "nl_confirm" in m.group(0), "ChatRequest 未声明 nl_confirm 字段"


def test_chat_确认拦截分支() -> None:
    """/chat 在 merge 前拦截：confirm_required 响应 + pending_params 下发，
    不调 apply_turn_guarded（不进引擎）。"""
    src = _web_server()
    assert '"confirm_required": True' in src, "确认响应缺 confirm_required"
    assert '"pending_params"' in src, "确认响应缺 pending_params"
    # 拦截分支必须在 apply_turn_guarded 之前形成早退
    m = re.search(r"if should_merge and [\s\S]*?confirm_required[\s\S]*?return JSONResponse", src)
    assert m, "未找到「should_merge 且确认开 → 早退」拦截分支"


def test_前端请求带nl_confirm() -> None:
    """send() 请求体带 nl_confirm（产品默认开：skip 开关只影响真假值）。"""
    src = _app_js()
    m = re.search(r"const body = \{ messages[\s\S]*?fetch\('/chat'", src)
    assert m, "send() 请求构造区找不到"
    assert "nl_confirm" in m.group(0), "send() 未发送 nl_confirm"


def test_前端确认响应分支() -> None:
    """send() 对 confirm_required 分支处理：pending 参数进表单待确认。"""
    src = _app_js()
    assert "confirm_required" in src, "前端无 confirm_required 分支"
    assert "pending_params" in src, "前端未消费 pending_params"
    assert "pendingNLParams" in src, "无 pendingNLParams 模块态（表单渲染数据源）"


def test_确认条三件套() -> None:
    """确认条：pf-confirm 容器 + 确认开算（pf-confirm-ok，落点 saveParamsForm=PUT）
    + 忽略（pf-confirm-ignore，回滚表单到引擎现值）。"""
    src = _app_js()
    assert "pf-confirm" in src, "确认条容器缺失"
    assert "确认开算" in src, "「确认开算」按钮缺失"
    assert "pf-confirm-ok" in src, "确认开算按钮类缺失"
    assert "pf-confirm-ignore" in src, "忽略按钮缺失"


def test_待确认来源标() -> None:
    """pending 字段在表单中标「待确认」（psrc-pending），与 [用户]/[默认] 同位。"""
    src = _app_js()
    assert "psrc-pending" in src, "[待确认] 来源标缺失"
    assert "待确认" in src, "待确认文案缺失"


def test_跳过开关() -> None:
    """「NL 免确认直接生效」设置：localStorage nl_confirm_skip + 表单底栏复选框。"""
    src = _app_js()
    assert "nl_confirm_skip" in src, "localStorage 设置键缺失"
    assert "pf-skip-confirm" in src, "跳过开关复选框缺失"


def test_确认落点是saveParamsForm() -> None:
    """确认开算必须复用 saveParamsForm（PUT 唯一真源），不许新写提交路径。"""
    src = _app_js()
    m = re.search(r"pf-confirm-ok[\s\S]{0,400}?saveParamsForm\(\)", src)
    assert m, "确认开算未复用 saveParamsForm——出现第二条提交路径（五个不许第一条）"
