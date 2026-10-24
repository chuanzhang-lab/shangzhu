"""M-04 契约测试：GET /form-schema 必须与 field_model 一致（纯投影）。

背景：表单将成为主输入（M-05 schema 驱动渲染），字段口径的唯一真源是
field_model 的 INPUT_SPECS/DERIVED_SPECS——端点只许投影，不许自己另编
字段清单（否则表单和引擎两套口径，改一处漏一处）。

一致性断言（计划 M-04 验收：「下发与 field_model 一致」）：
- input_fields 名称集 == INPUT_SPECS ∪ OVERRIDABLE_FIELDS
- label/unit 逐字段与 field_model 相同
- derived_fields 名称集 == DERIVED_SPECS；deps/kind 透传；lambda 不外泄
- groups 覆盖恰好全部可编辑字段（无悬空引用、无遗漏）
- templates == 12 行业
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from fastapi.testclient import TestClient  # noqa: E402

_SPEC_KEYS = {"name", "label", "unit", "type", "kind"}
_DERIVED_KEYS = {"name", "label", "unit", "kind", "deps", "user_direct_ok"}


def _get():
    import web_server as ws
    tc = TestClient(ws.app)
    r = tc.get("/form-schema")
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    return r.json()


def test_schema_shape():
    body = _get()
    for key in ("version", "input_fields", "derived_fields", "groups", "templates"):
        assert key in body, f"缺 {key}"


def test_input_fields_match_field_model():
    from field_model import INPUT_SPECS, OVERRIDABLE_FIELDS
    body = _get()
    names = {f["name"] for f in body["input_fields"]}
    assert names == set(INPUT_SPECS) | set(OVERRIDABLE_FIELDS), (
        f"可编辑字段集不一致: 多 {names - (set(INPUT_SPECS) | set(OVERRIDABLE_FIELDS))}, "
        f"少 {(set(INPUT_SPECS) | set(OVERRIDABLE_FIELDS)) - names}"
    )
    by_name = {f["name"]: f for f in body["input_fields"]}
    for n, spec in INPUT_SPECS.items():
        assert by_name[n]["label"] == spec["label"], f"{n} label 漂移"
        assert by_name[n]["unit"] == spec.get("unit", ""), f"{n} unit 漂移"
    # kind 口径：可覆盖字段必须标 override（前端据此渲染「覆盖公式」态）
    for n in OVERRIDABLE_FIELDS:
        assert by_name[n]["kind"] == "override", f"{n} 应标 override"


def test_derived_fields_projection_no_lambda_leak():
    from field_model import DERIVED_SPECS
    body = _get()
    names = {f["name"] for f in body["derived_fields"]}
    assert names == set(DERIVED_SPECS), f"派生字段集不一致: {names ^ set(DERIVED_SPECS)}"
    for f in body["derived_fields"]:
        spec = DERIVED_SPECS[f["name"]]
        assert set(f.keys()) <= _DERIVED_KEYS, f"{f['name']} 泄漏了非白名单键"
        assert f["deps"] == list(spec.get("deps", [])), f"{f['name']} deps 漂移"
        assert f["user_direct_ok"] == bool(spec.get("user_direct_ok", False))


def test_groups_cover_all_editable_exactly():
    from field_model import INPUT_SPECS, OVERRIDABLE_FIELDS, PARAM_GROUPS
    editable = set(INPUT_SPECS) | set(OVERRIDABLE_FIELDS)
    grouped = [f for g in PARAM_GROUPS for f in g["fields"]]
    assert set(grouped) == editable, (
        f"分组与可编辑字段不一致: 悬空 {set(grouped) - editable}, "
        f"遗漏 {editable - set(grouped)}"
    )
    assert len(grouped) == len(set(grouped)), "字段被分到多个组（重复）"
    body = _get()
    assert body["groups"] == PARAM_GROUPS, "groups 下发与 SSOT 不一致"


def test_templates_twelve_industries():
    body = _get()
    tpl = body["templates"]
    assert isinstance(tpl, dict) and len(tpl) == 12, f"模板数 {len(tpl)} != 12"
    for name, t in tpl.items():
        assert "hypotheses" in t, f"{name} 缺 hypotheses（M-06 预填依赖）"


def test_version_stable_across_calls():
    assert _get()["version"] == _get()["version"], "同 mtime 下版本指纹必须稳定"
