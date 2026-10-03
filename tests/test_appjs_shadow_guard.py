"""app.js 变量遮蔽护栏（M-03，静态扫描，不执行 JS）。

背景（2026-10-01 真实故障，shangzhu-en 同类护栏移植）：EN 版 i18n 迁移后全局翻译
函数叫 `t`，任务对象参数也叫 `t`——`tasks.forEach(t => ...)` / `taskMenu(t, div)`
参数遮蔽翻译函数，`t('ui.xxx')` 变成「拿任务对象当函数调」→ TypeError → 被 catch
吞掉 → 前端整片静默损坏。中文版虽无翻译函数，但同名参数是复发温床（引入 i18n 即炸）。

规则（比 ESLint 的点状检查更贴本项目事故形态）：
1. 函数参数/箭头形参禁止命名为 `t`（翻译函数预留名 + 单字母可读性差）；
2. 函数体内禁止 `const/let/var input`（遮蔽全局聊天输入框 `input`，app.js:3）；
3. 函数体内禁止 `const/let/var taskList/taskMenu/empty/chat` 等全局名的局部声明。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(ROOT, "src", "web_static", "app.js")

_FUNC_RE = re.compile(r"^\s*(?:async\s+)?function\s+\w+\s*\(([^)]*)\)")
_ARROW_PARAM_RE = re.compile(r"\(([^()]*)\)\s*=>")
_DECL_RE = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)")

# 全局名（app.js 顶层 const/let 声明）——函数体内不得再声明同名局部变量
GLOBAL_NAMES = ["input", "taskList", "empty", "chat", "catBtns", "currentTaskId"]
_DECL_BANNED = re.compile(
    r"\b(?:const|let|var)\s+(" + "|".join(GLOBAL_NAMES) + r")\b"
)


def _read_lines():
    with open(APP_JS, encoding="utf-8") as f:
        return f.read().splitlines()


def test_no_param_named_t():
    """参数禁止叫 `t`：翻译函数遮蔽事故的直接温床。"""
    offenders = []
    for i, line in enumerate(_read_lines(), 1):
        for m in (_FUNC_RE.match(line),):
            if m:
                params = [p.strip() for p in m.group(1).split(",") if p.strip()]
                if any(re.fullmatch(r"t", p) for p in params):
                    offenders.append((i, line.strip()))
        for m in _ARROW_PARAM_RE.finditer(line):
            params = [p.strip() for p in m.group(1).split(",") if p.strip()]
            if any(re.fullmatch(r"t", p) for p in params):
                offenders.append((i, line.strip()))
    assert not offenders, (
        "app.js 存在名为 `t` 的函数参数（遮蔽翻译函数的事故形态），请改名 `task`：\n"
        + "\n".join(f"  L{i}: {ln}" for i, ln in offenders)
    )


def test_no_local_shadow_of_globals():
    """函数体内禁止声明与全局同名的局部变量（input/taskList/... 遮蔽）。"""
    offenders = []
    for i, line in enumerate(_read_lines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        # 跳过顶层声明行本身（全局声明是合法的）
        if re.match(r"^(export\s+)?(const|let|var)\s", stripped):
            continue
        m = _DECL_BANNED.search(line)
        if m:
            offenders.append((i, line.strip()))
    assert not offenders, (
        "app.js 函数体内声明了与全局同名的局部变量（遮蔽全局，易出静默错误）：\n"
        + "\n".join(f"  L{i}: {ln}" for i, ln in offenders)
    )
