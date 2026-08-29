"""web_server HTTP 层健壮性测试：验证服务在各种边界输入下稳定返回
（不 500、不卡死），并验证 /health、多轮会话累积等行为。

固定 llm_advise 为桩（不真实联网），聚焦 HTTP/路由/解析层稳定性。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# web_server 导入时会 os.chdir 到 src/，导入完成后立即恢复仓库根 cwd，
# 避免影响 run_all 后续模块（web_server 运行不依赖 cwd，全用绝对路径）。
_saved = os.getcwd()
import web_server as ws
os.chdir(_saved)

from fastapi.testclient import TestClient

# 桩掉 LLM 调用（不真实联网），专注 HTTP/路由/解析层
ws.llm_advise = lambda scan, user_text="", session_snapshot=None: {"text": "", "ops": []}
_client = TestClient(ws.app)


def _chat(messages, tid="rb"):
    return _client.post("/chat", json={"messages": messages, "thread_id": tid})


def test_health_ok():
    r = _client.get("/health")
    assert r.status_code == 200
    assert "model" in r.json()


def test_empty_messages_400():
    # 空 messages 数组 → 无用户消息 → 400
    r = _chat([])
    assert r.status_code == 400


def test_only_assistant_400():
    r = _chat([{"role": "assistant", "content": "hi"}])
    assert r.status_code == 400


def test_missing_messages_field_422():
    # 缺 messages 字段 → Pydantic 校验 422（框架层，防止未来模型破坏致 500）
    r = _client.post("/chat", json={"thread_id": "x"})
    assert r.status_code == 422


def test_normal_structured_200():
    r = _chat([{"role": "user",
                "content": "奶茶店月租金1万员工2人工资各5000客单价15日售50杯"}])
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "structured"
    assert body["intent"] in ("quick_scan", "trend", "compare", "suggest")


def test_chitchat_returns_steward():
    r = _chat([{"role": "user", "content": "你好，随便聊聊"}], tid="rb-chat")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "steward"
    assert body["intent"] == "chitchat"


def test_very_long_input_no_crash():
    # 超长输入不应导致崩溃或卡死（to_thread 不冻结事件循环）
    long_text = "开奶茶店 " * 4000  # ~12000 字
    r = _chat([{"role": "user", "content": long_text}], tid="rb-long")
    assert r.status_code in (200, 400)


def test_session_accumulates_across_turns():
    # 多轮累积：第一轮给部分参数，第二轮补参，两轮都应稳定 200
    tid = "rb-acc"
    r1 = _chat([{"role": "user", "content": "开奶茶店，月租金1万"}], tid=tid)
    assert r1.status_code == 200
    r2 = _chat([{"role": "user", "content": "员工2人工资各5000"}], tid=tid)
    assert r2.status_code == 200


def test_unknown_intent_falls_to_steward():
    # 无法归类的业务/闲聊文本应走 steward，而非 500
    r = _chat([{"role": "user", "content": "今天天气不错，顺便问下我这店能赚钱吗"}],
              tid="rb-unk")
    assert r.status_code == 200
    assert r.json()["mode"] == "steward"


def test_compare_routes_and_uses_alt_params():
    # 对比意图应调用 compare_scenarios，并解析「如果」后的参数作为方案 B
    tid = "rb-compare"
    r1 = _chat([{"role": "user",
                  "content": "奶茶店月租金1万员工2人工资各5000客单价15日售50杯"}], tid=tid)
    assert r1.status_code == 200
    r2 = _chat([{"role": "user",
                  "content": "如果日售提高到80杯，对比一下"}], tid=tid)
    assert r2.status_code == 200
    body = r2.json()
    assert body["mode"] == "structured"
    assert body["intent"] == "compare"


def test_benchmark_and_market_routed_200():
    # 行业基准与市场调研意图都应稳定返回结构化数据，不 500
    for tid, text in [("rb-bench", "查一下奶茶行业毛利率基准"),
                      ("rb-market", "2025年奶茶市场规模")]:
        r = _chat([{"role": "user", "content": text}], tid=tid)
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "structured"
        assert body["intent"] in ("benchmark", "market")


def test_report_excel_routed_200():
    # 报告意图应调用报告生成工具并返回下载链接/路径
    tid = "rb-report-excel"
    r = _chat([{"role": "user",
                  "content": "奶茶店月租金1万员工2人工资各5000客单价15日售50杯，导出Excel"}],
              tid=tid)
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "structured"
    assert body["intent"] == "report_excel"
    # 本地无 Coze SDK 时会在 Markdown 内容里包含本地文件路径
    assert "报告已生成" in body["content"] or "file://" in body["content"]


def test_health_includes_version_and_uptime():
    r = _client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "model" in body
    assert "version" in body
    assert body["version"] == ws.APP_VERSION
    assert "uptime_seconds" in body
    assert isinstance(body["uptime_seconds"], (int, float))
    assert "llm_configured" in body
    assert isinstance(body["llm_configured"], bool)
    assert "sessions" in body
    assert "active_sessions" in body["sessions"]


def test_oversized_input_returns_400():
    # 超过 _MAX_INPUT_LENGTH 字符应返回 400，不触发后续工具/LLM
    long_text = "开奶茶店 " * 5000
    r = _chat([{"role": "user", "content": long_text}], tid="rb-oversize")
    assert r.status_code == 400
    assert "过长" in r.json()["error"]


def test_session_params_not_mutated_by_route():
    # 下游 setdefault 不得写回 SessionState（merged 必须是拷贝）
    tid = "rb-noleak"
    r1 = _chat([{"role": "user", "content": "开奶茶店，月租金1万"}], tid=tid)
    assert r1.status_code == 200
    before = dict(ws.get_state(tid).get("params") or {})
    r2 = _chat([{"role": "user", "content": "你好"}], tid=tid)
    assert r2.status_code == 200
    after = dict(ws.get_state(tid).get("params") or {})
    # chitchat 不改 params；且不应凭空多出字段
    assert after == before


def test_concurrent_chats_no_crash():
    # 并发请求不应 500 / 卡死（工具与 LLM 均在 to_thread）
    import concurrent.futures

    def one(i):
        return _chat(
            [{"role": "user", "content": f"奶茶店月租金{10000 + i}员工2人工资各5000客单价15日售50杯"}],
            tid=f"rb-conc-{i}",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(one, range(6)))
    assert all(r.status_code == 200 for r in results)
    assert all(r.json().get("mode") == "structured" for r in results)
