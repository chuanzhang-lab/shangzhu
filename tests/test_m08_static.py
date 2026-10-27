"""M-08 静态守卫（2026-10）：收尾——旧改参区删除 / 仓洁 / 文档齐 / e2e 守卫全铺。

计划 M-08 行：.gitignore 补 .zcodeignore/工具产物；README/AGENT.md 更新；
灰度开关定稿（确认层跳过开关已在 M-07 落地，本文件钉其不再回退）。
旧改参区（pcFields/pcRecalc）按计划 6.10「保留一版，M-06 后删」到期删除，
其「PUT 唯一真源」不变量由 test_put唯一写入口 重新承接（M-06 的
test_pcrecalc改调put 随 UI 删除而退役）。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "src" / "web_static" / "app.js"
APP_CSS = ROOT / "src" / "web_static" / "app.css"
WEB_SERVER = ROOT / "web_server.py"
GITIGNORE = ROOT / ".gitignore"
README = ROOT / "README.md"
AGENT_MD = ROOT / "AGENT.md"
E2E_DIR = ROOT / "tests" / "e2e"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_gitignore_补工具产物() -> None:
    """P-07：.zcodeignore 等工具产物不入库。"""
    gi = _read(GITIGNORE)
    assert ".zcodeignore" in gi, ".gitignore 缺 .zcodeignore"


def test_旧改参区前端已删() -> None:
    """旧改参区（计划 6.10 保留一版后删）：app.js 四件套必须零残留，
    残留的 null.style 引用会在运行时 TypeError。"""
    src = _read(APP_JS)
    for token in ("pcRecalc", "pcFields", "renderParamFields", "paramsControls"):
        assert token not in src, f"app.js 仍残留旧改参区标记: {token}"


def test_旧改参区页面样式已删() -> None:
    """页面 HTML（web_server 内嵌）与样式同步删除——DOM 留着 JS 删了，
    等于给用户留一个死按钮。"""
    assert "params-controls" not in _read(WEB_SERVER), "web_server 页面 HTML 仍含 #params-controls"
    assert ".pc-recalc" not in _read(APP_CSS), "app.css 仍含 .pc-recalc 样式"


def test_put唯一写入口() -> None:
    """执行简报「五个不许」第一条的静态面：params PUT 的 URL 构造点
    全仓唯一（submitParams；任务改名等无关 PUT 不在此列）。
    新出现的第二处 = 另写了参数更新路径。"""
    src = _read(APP_JS)
    n = src.count("currentTaskId + '/params'")
    assert n == 1, f"app.js 出现 {n} 处 params URL 构造——唯一真源被破坏"


def test_readme_输入层文档齐() -> None:
    """README 界面与 API 段：表单/PUT/确认层三特性入文档。"""
    src = _read(README)
    assert "PUT /tasks/{id}/params" in src, "README 缺 PUT /tasks/{id}/params 接口行"
    assert "/form-schema" in src, "README 缺 GET /form-schema 接口行"
    assert "确认" in src and "表单" in src, "README 未描述表单 + 确认层输入模型"


def test_agent_md_输入层规格() -> None:
    """AGENT.md：参数输入层架构规格（三层输入 / 确认层 / 唯一写入口）。"""
    src = _read(AGENT_MD)
    assert "确认层" in src, "AGENT.md 缺确认层规格"
    assert re.search(r"唯一写入口|唯一真源", src), "AGENT.md 缺「PUT 唯一写入口」约束"


def test_e2e_端口守卫全铺() -> None:
    """M-07 教训（孤儿 uvicorn 占端口 → 测试静默打到旧代码服务器）：
    五件 e2e 必须都有 server.exitCode 端口冲突守卫。"""
    missing = []
    for name in ("smoke.mjs", "advice.mjs", "form.mjs", "template.mjs", "confirm.mjs"):
        p = E2E_DIR / name
        if not p.exists() or "server.exitCode" not in _read(p):
            missing.append(name)
    assert not missing, f"缺端口冲突守卫的 e2e: {missing}"