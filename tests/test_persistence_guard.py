"""持久化依赖声明护栏（环境无关，不要求本机装 PostgreSQL / psycopg）。

背景：psycopg 曾只声明在可选依赖组（旧 coze-platform extra）里，`uv sync`
把它从 .venv 剪掉 → PostgresStore 延迟导入失败 → 静默降级 → 任务数据重启即丢
（详见 src/storage/local_store.py 模块注释「历史教训」）。

本护栏只做声明级检查，与运行环境解耦：
1. pyproject.toml 主依赖 dependencies 必须声明 psycopg——防再次被任何
   extra/依赖组调整剪掉（本文件即 local_store.py 注释所指护栏的落地）；
2. local_store.py 顶层不得 import psycopg——驱动必须延迟到 PostgresStore
   内部导入，保证无驱动环境服务仍能启动并降级到 LocalFileStore。
"""

import os
import re
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_psycopg_declared_in_main_dependencies():
    """psycopg 必须声明在主依赖：它是 PostgresStore 主链路依赖，
    放进任何 optional extra 都会被 `uv sync` 剪掉（历史事故已发生）。"""
    data = tomllib.loads(_read(os.path.join(ROOT, "pyproject.toml")))
    deps = data["project"]["dependencies"]
    assert any(d.strip().lower().startswith("psycopg") for d in deps), (
        "pyproject.toml 主依赖缺少 psycopg——PostgresStore 主链路依赖会被 "
        "uv sync 剪掉，导致静默降级内存/文件存储、任务数据重启即丢"
        "（见 src/storage/local_store.py 模块注释「历史教训」）。"
    )


def test_local_store_psycopg_is_lazy_import():
    """local_store.py 顶层不得 import psycopg。

    顶层导入会让「未装驱动的机器」在 import 即崩，失去降级启动能力；
    驱动导入必须延迟到 PostgresStore 类内部（模块注释 40-42 行的设计约定）。
    """
    src = _read(os.path.join(ROOT, "src", "storage", "local_store.py"))
    assert re.search(r"import psycopg", src), (
        "local_store.py 缺少 psycopg 导入——PostgresStore 主链路疑似被删断"
    )
    for i, ln in enumerate(src.splitlines(), 1):
        if "import psycopg" in ln and ln.lstrip().startswith("#"):
            continue  # 注释里的字面提及不算
        assert not re.match(r"^(import|from)\s+psycopg", ln), (
            f"local_store.py 第 {i} 行在模块顶层导入 psycopg，"
            f"必须延迟到 PostgresStore 类内部：{ln.strip()!r}"
        )
