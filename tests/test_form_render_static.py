"""M-05 静态守卫：表单必须 schema 驱动，不许回退硬编码字段清单。

背景：旧面板硬编码 12 个 inputFields + fieldLabel 映射，「只渲染已有值」
导致缺参字段永远没入口（线上事故的表单侧根源）。M-05 起 app.js 必须从
/form-schema 拉口径渲染——本守卫钉住三件事，谁回退谁红：
1. app.js 必须请求 /form-schema（schema 驱动）；
2. 旧硬编码字段清单（const inputFields = [...]）必须已删；
3. 表单输入必须带 data-field（缺参可填的入口特征）。
运行期行为由 tests/e2e/form.mjs 锁（DOM 数 == schema 数 + PUT 闭环）。
"""
import os
import re

APP_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "src", "web_static", "app.js")


def _read():
    with open(APP_JS, encoding="utf-8") as f:
        return f.read()


def test_appjs_fetches_form_schema():
    js = _read()
    assert "/form-schema" in js, (
        "app.js 不再请求 /form-schema——表单已脱离 schema 驱动（口径回退硬编码）"
    )


def test_appjs_hardcoded_field_list_deleted():
    js = _read()
    assert not re.search(r"const\s+inputFields\s*=\s*\[", js), (
        "硬编码 inputFields 清单又回来了——字段口径必须来自 /form-schema，"
        "加字段要改 field_model 而不是 app.js"
    )


def test_appjs_form_inputs_have_data_field():
    js = _read()
    assert 'data-field' in js, "表单输入缺 data-field——缺参字段不可填（M-05 验收特征丢失）"
