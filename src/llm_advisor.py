"""Phase 2 · LLM 协作层（轻量、被动、只读）

把 quick_scan / trend / compare 的「结构化输出」（置信层、情景、叙事、假设清单）
接进项目已有的 DeepSeek 通道，生成自然语言解读与建议。

设计原则（护栏）：
- 被动：仅在业务结果生成后调用，不主动发起、不在用户沉默时骚扰。
- 只读：只消费结构化输出 JSON，不调任何工具、不写文件、不修改状态。
- 复用：沿用 config/agent_llm_config.json 的 DeepSeek 配置与 DEEPSEEK_API_KEY。
- 兜底：无 key 或调用失败 → 返回空字符串，绝不阻断主流程（规则渲染照常返回）。

注意：本模块的 prompt 与 agent.py 中「不聊天/不给建议」的系统提示词是**两套独立通道**——
agent.py 管 chitchat 闲聊路径，本模块管「基于标注给建议」的业务解读路径，互不干扰。
"""
import os
import json
import logging
import copy
import re
import tempfile
import threading
from pathlib import Path

import requests
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)
# LLM 通道的合理上限：聊天 UI 单次调用不应阻塞过久（原 300s 过长）。
# 配合 web_server 用 asyncio.to_thread 调用，即使触发超时也只挂起该请求，
# 不会冻结整个事件循环。
_LLM_TIMEOUT = 60
_llm_cache_lock = threading.Lock()

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"  # 默认值，实际优先从 config 读取


def _api_key_from_keyring(service: str, account: str) -> str:
    """从 macOS Keyring 读取 API key，读不到返回空串。"""
    import subprocess
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def _api_key_from_env() -> str:
    """从环境变量读取 API key（兼容多厂商变量名）。"""
    for var in ("DEEPSEEK_API_KEY", "LONGCAT_API_KEY", "LLM_API_KEY"):
        v = os.getenv(var, "").strip()
        if v:
            return v
    return ""


def _api_key_from_config() -> str:
    """从 config JSON 读取 API key（配置单源，与 model/base_url 同源）。"""
    try:
        cfg = _load_llm_config()
        return (cfg.get("config", {}) or {}).get("api_key", "").strip()
    except Exception:
        return ""


def _api_key() -> str:
    """运行期读取 API key，配置单源优先（config → env → keyring）。

    1) config/agent_llm_config.json（用户在设置页保存的 key，与 model/base_url 同源）
    2) 环境变量 (DEEPSEEK_API_KEY / LONGCAT_API_KEY / LLM_API_KEY)
    3) macOS Keyring (service="shangzhu-llm", account="api_key")
    4) 空串（未配置）

    config 必须优先：model / base_url 已经「配置单源」从 config 读取，若 key 反而
    优先取环境变量，会出现「config 指向 LongCat、而 env 残留 DEEPSEEK_API_KEY(sk-…)」
    的跨厂商错配，导致 401 invalid_api_key（无效的AppId）。env / keyring 仅在 config
    未写 key 时兜底，兼容纯环境变量 / Keyring 部署。
    """
    # 1) config（与 model/base_url 同源）
    key = _api_key_from_config()
    if key:
        return key

    # 2) env（兜底，兼容未在设置页存 key 的部署）
    key = _api_key_from_env()
    if key:
        return key

    # 3) keyring
    key = _api_key_from_keyring("shangzhu-llm", "api_key")
    if key:
        return key

    return ""

# 配置路径自愈：优先 COZE_WORKSPACE_PATH，其次本文件上两级仓库根，
# 最后 cwd。不依赖 web_server 是否先设环境变量，import 即用。
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _resolve_llm_config_path() -> str:
    candidates = []
    env_ws = os.getenv("COZE_WORKSPACE_PATH", "").strip()
    if env_ws:
        candidates.append(Path(env_ws) / "config" / "agent_llm_config.json")
    candidates.append(_REPO_ROOT / "config" / "agent_llm_config.json")
    candidates.append(Path.cwd() / "config" / "agent_llm_config.json")
    for p in candidates:
        try:
            if p.is_file():
                return str(p)
        except OSError:
            continue
    # 兜底：返回首选路径（_load 失败时用内置默认）
    return str(candidates[0] if candidates else "config/agent_llm_config.json")


LLM_CONFIG_PATH = _resolve_llm_config_path()

_SYSTEM = """你是「创业者商业建模工作台」的**交互主持人**——用户的私人创业分析顾问。

你的核心角色是**翻译 + 追问 + 推荐**：
### 1. 翻译（把数字变成决策）
- 把引擎输出的结构化数据（月利润、跑道、盈亏平衡点）翻译成用户能理解的语言
- 不只是报数字，还要解释**为什么重要**："月利润 5000，跑道 5 个月偏紧——一般建议至少 6 个月缓冲"
- 把数字翻译成画面感："每月落袋 5000，够覆盖..."

### 2. 追问（引导用户补参数）
- 缺核心参数时，追问 1-2 个最关键的（月租、客流、客单价、员工数）
- 每轮追问都给"先用默认值算一下"选项："月租多少？没概念的话先用 8000 算一下"
- 追问有明确目标，不是漫无目的

### 3. 推荐（从引擎给的动作列表里选）
- 参数充足时，推荐下一步最该看的分析（从引擎提供的 available_actions 里选）
- 每轮最多推荐一个动作，结尾问"要不要看看？"
- 连续两轮推荐后，第三轮起不再推荐，等用户指令

## 铁律（不可破）
- 你看到的「结构化分析结果 + 当前会话状态 + 本轮变更」即唯一真相。绝不声称引擎错了、绝不与历史原文对账。
- **任何面向用户的数字必须来自结构化输出，绝不在体内做算术**
- **绝不评价参数好坏**："月租 1 万偏高" ❌ → "月租 1 万占成本 40%，比行业平均高 5 个百分点" ✅
- **绝不替用户做决定**："我建议你提价" ❌ → "要不要看看提价的影响？" ✅
- 绝不修改派生字段（monthly_labor / monthly_fixed_cost / monthly_profit 等靠引擎重算，不让人改）。
- **绝不自行分析趋势/做推断**：所有分析是引擎的事

## 编排能力（Tier 1，受代码校验后由用户确认）
- 用户给模糊目标时，在回复末尾输出 ```ops 块，给骨架只给方向不给死值：

  ```ops
  [
    {"propose": "try", "label": "提价3元", "changes": {"price_per_unit": 18}, "reason": "看提价能否扭亏"},
    {"propose": "try", "label": "客流+10/天", "changes": {"daily_traffic": 60}, "reason": "看客流提升能否扭亏"}
  ]
  ```

  或单值改动：

  ```ops
  [
    {"propose": "set", "field": "avg_salary", "value": 3000, "reason": "用户明确要求改为3000元"}
  ]
  ```

  web 端会逐条算预览，把「方案X→月利润Y」回贴给你看，用户回「应用X」才生效。你只提议，不执行。

- 编排只针对「基础字段」。派生字段、模板配置、行业默认 一律不可在 ops 里出现。
- 用户已明确给出精确参数时（如「人工改为2*3000」），抽取器会自动处理掉，**不要输出 ops**，只解读后果即可。

语气：简洁、直接、不寒暄、不喊口号。一次最多给一个真正的下一步追问。
"""


# L2 决策模式系统提示（D5/D6：选项+风险+作废条件，绝不含倾向/判决/命令）
_SYSTEM_DECISION = """你是「验证期决策工作台」的决策解说员——只把结构化决策讲清楚，不替用户拍板。

输入是规则层算好的决策结果（客观结论 + 候选调整 + 先验证什么）。你的任务：
1) 用人话转述「客观结论」的数字与含义（月利润、距盈亏平衡、跑道）。
2) 把每个候选调整讲成「选项 + 代价/风险」，不要预言哪个一定好。
3) 把「先验证什么」的最小实验讲成可执行的一步。
4) 若用户给了自己的底线（现金、最长可亏月数、能接受的回本周期），只在转述里体现，不下判决。

铁律（不可破，命中即违规）：
- 禁止一切倾向/命令/判决类措辞（"我建议你开/关"、"你应该提价"、"千万别继续"这类一律不准）。
- 禁止说「我建议关店 / 我建议继续 / 你该提价」这类代替用户拍板的话。
- 禁止在体内做任何算术；所有数字必须来自输入的结构化结果。
- 我不执行任何 ops 的写入；如需调整，说明「可回『应用X』试这一项」，绝不替用户决定要不要应用。
- 用户问「那你说我到底该不该」，你可以重申客观数字 + 反问他的底线（现金能撑多久/可接受风险），把决定权交还给他。
"""


def _is_decision_scan(scan: dict) -> bool:
    """识别结构化决策结果（decision_engine.decide 产物）。"""
    if not isinstance(scan, dict):
        return False
    return ("type" in scan and "confidence" in scan
            and ("options" in scan or "conclusion" in scan or "gaps" in scan))



def _load_llm_config() -> dict:
    # 每次解析路径，支持运行期切换 COZE_WORKSPACE_PATH / 工作目录
    path = _resolve_llm_config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.debug("LLM config load failed (%s): %s", path, e)
        return {
            "config": {
                "model": "deepseek-v4-flash",
                "temperature": 0.3,
                "timeout": _LLM_TIMEOUT,
            }
        }


def get_model_name() -> str:
    """配置单源：模型名统一从 config/agent_llm_config.json 读取（web_server / 本模块共用）。"""
    return _load_llm_config().get("config", {}).get("model", "deepseek-v4-flash")


def get_base_url() -> str:
    """配置单源：LLM 端点，优先从 config 读，fallback 到默认常量。"""
    try:
        cfg = _load_llm_config()
        url = (cfg.get("config", {}) or {}).get("base_url", "")
        if url:
            return url.strip()
    except Exception:
        pass
    return DEEPSEEK_BASE_URL


def has_api_key() -> bool:
    """是否已配置 DEEPSEEK_API_KEY（供 /health 可观测性）。"""
    return bool(_api_key())


def _build_brief(scan: dict, changes: dict = None) -> str:
    """把结构化分析结果压成给 LLM 的紧凑简报。

    changes：本轮参数变更（来自 session_state._last_changes），让 LLM
    基于「变化」讲解，而不是去翻历史原文猜（对账幻觉的根因）。
    """
    lines: list[str] = []

    # 本轮变更置顶——这是用户当下最在意的，也是避免 LLM 翻历史原文的关键
    if changes:
        lines.append("本轮已更新的参数：")
        for k, d in changes.items():
            kind = d.get("kind", "changed")
            frm = d.get("from")
            to = d.get("to")
            if kind == "added" and to is not None and not str(to).startswith("_"):
                lines.append(f"  - {k}: 新增={to}")
            elif kind == "changed" and to is not None and not str(to).startswith("_"):
                lines.append(f"  - {k}: {frm} → {to}")
            elif kind == "removed":
                lines.append(f"  - {k}: 已删除（原 {frm}）")
        lines.append("")

    pt = scan.get("project_type") or scan.get("industry_name") or "未知行业"
    lines.append(f"项目类型：{pt}")

    if scan.get("insufficient"):
        lines.append("状态：参数不足（已暂停完整分析）")
        gaps = scan.get("gaps", [])
        if gaps:
            lines.append("待补字段：" + "、".join(gaps))
    else:
        cm = scan.get("core_metrics", {})
        if cm:
            lines.append("核心指标：")
            for k in ("monthly_revenue", "monthly_fixed_cost", "monthly_profit", "runway_months"):
                if k in cm:
                    lines.append(f"  - {k}: {cm[k]}")
        # 人工分解（让 LLM 看到权威值，不再去翻历史原文猜）
        params = scan.get("params") or {}
        if params.get("monthly_labor") is not None:
            lines.append(
                f"  - 人工裸薪: {params.get('monthly_labor_cash')} "
                f"含负担: {params.get('monthly_labor')} "
                f"(负担率 {params.get('labor_burden_rate')})"
            )

    # 情景区间
    sc = scan.get("scenarios")
    if sc and sc.get("has_uncertainty"):
        mp = sc.get("monthly_profit", {})
        lines.append(
            f"情景区间：月利润 乐观 {mp.get('best')} / 中性 {mp.get('base')} / 保守 {mp.get('worst')}"
        )
        drivers = sc.get("drivers") or []
        if drivers:
            lines.append("不确定来源：" + "、".join(drivers))

    # 叙事（已含风险杠杆，直接复用）
    if scan.get("narrative"):
        lines.append("风险聚焦：" + scan["narrative"])

    # 假设清单
    asm = scan.get("assumptions") or []
    if asm:
        lines.append("当前假设：")
        for a in asm:
            lines.append(f"  - {a.get('field')}: {a.get('value')} 来源={a.get('source')}")

    # 置信概览
    if scan.get("confidence"):
        lines.append(f"置信概览：{scan['confidence']}")

    return "\n".join(lines)


def _emit_anomaly_report(scan: dict):
    """引擎健康监控（运维闭环）：发现参数矛盾 / 极端异常，输出结构化 AnomalyReport 至日志。

    这是「提议权」而非「执行权」——绝不运行时 exec/eval/写文件，仅供人工 review 后落地。
    返回 report dict（若有异常）或 None。
    """
    src = scan.get("param_sources") or {}
    anomalies = []
    for k, v in src.items():
        if isinstance(v, str) and "矛盾" in v:
            anomalies.append({"field": k, "source": v})
    # 极端固定成本（疑似抽取误抓，如被误抓成 1.0）
    fc = (scan.get("params") or {}).get("monthly_fixed_cost")
    if isinstance(fc, (int, float)) and fc == 1.0:
        anomalies.append({"field": "monthly_fixed_cost", "source": f"异常值 {fc}（疑似抽取误抓）"})
    if not anomalies:
        return None
    report = {
        "type": "AnomalyReport",
        "detected_at": "runtime",
        "anomalies": anomalies,
        "proposed_fix": "核对用户输入与抽取器，确认组件聚合(C1)优先级或显式总数处理",
        "should_cover_test": "tests/test_phase4_workbench.py",
    }
    logger.warning("Engine anomaly detected: %s", json.dumps(report, ensure_ascii=False))
    return report


_llm_cache = None


def _get_llm() -> ChatOpenAI:
    global _llm_cache
    # 加锁：web_server 用线程池并发调用时，多个首调可能同时触发初始化竞态。
    with _llm_cache_lock:
        key = _api_key()
        cfg = _load_llm_config().get("config", {})
        model = cfg.get("model", "deepseek-v4-flash")
        base_url = get_base_url()
        # 配置变更时重建客户端（key/model/base_url 任一变化即刷新）
        cache_sig = (key, model, base_url)
        if _llm_cache is None or getattr(_llm_cache, "_shangzhu_sig", None) != cache_sig:
            cfg = _load_llm_config().get("config", {})
            # timeout 上限钳制，防止配置写成 300s 拖垮并发
            timeout = cfg.get("timeout", _LLM_TIMEOUT)
            try:
                timeout = min(float(timeout), float(_LLM_TIMEOUT))
            except (TypeError, ValueError):
                timeout = _LLM_TIMEOUT

            # 绕过代理：当 HTTP_PROXY 环境变量设置时，LLM API 请求可能因代理
            # 无法到达 api.longcat.chat 而超时。将 API 域名加入 NO_PROXY 绕过代理。
            from urllib.parse import urlparse
            _parsed = urlparse(base_url)
            _domain = _parsed.hostname
            if _domain:
                for _var in ("NO_PROXY", "no_proxy"):
                    _old = os.environ.get(_var, "")
                    if _domain not in _old:
                        os.environ[_var] = f"{_domain},{_old}" if _old else _domain

            client = ChatOpenAI(
                model=model,
                api_key=key,
                base_url=base_url,
                temperature=cfg.get("temperature", 0.3),
                timeout=timeout,
                max_completion_tokens=cfg.get("max_completion_tokens"),
                streaming=False,
            )
            client._shangzhu_sig = cache_sig  # type: ignore[attr-defined]
            _llm_cache = client
    return _llm_cache


def advise(scan: dict, user_text: str = "", session_snapshot: dict = None, context: dict = None) -> dict:
    """基于结构化输出生成 LLM 解读（交互主持人模式）。

    返回 {"text": 解读文本, "ops": [op...], "meta": {asked_question, made_recommendation}}：
    - text：自然语言解读（含追问/类比/翻译/推荐）
    - ops：若 LLM 输出了 ```ops 块则解析出的编排提议，由 web_server 渲染为确认流
    - meta：告诉引擎侧 LLM 做了什么（用于更新计数器）

    护栏（C3 红线，执行机制而非口号）：
    - 入参 scan / session_snapshot 一律先做 `copy.deepcopy` 只读副本，函数体
      不持有任何写引用，绝不修改调用方数据 / SessionState / 计算结果。
    - 任何面向用户的数字必来自 scan（引擎算的）；本函数体内不得出现算术表达式。
    - 引擎健康巡检（AnomalyReport）仅读 + 告警，绝不运行时 exec/eval/写文件。
    - **关键防幻觉**：脱稿 raw_text——snap_ro 中含历史用户原文（如早期『人工3500*2』），
      喂给 LLM 会引发『引擎还在用旧值』式对账幻觉。这里只用 params/industry/last_changes，
      不喂原文。
    无 key 或失败时 text 为空字符串、ops 为空列表，绝不阻断主流程。
    """
    # 只读护栏：拿到独立副本，任何后续误改都不影响调用方
    scan_ro = copy.deepcopy(scan or {})
    snap_ro = copy.deepcopy(session_snapshot or {})

    # 引擎健康巡检（运维闭环，仅读 + 告警，不落地）
    _emit_anomaly_report(scan_ro)

    if not _api_key():
        return {"text": "", "ops": []}

    # 提取本轮变更（LLM 基于变化讲，不去翻历史原文）
    changes = snap_ro.get("last_changes") if isinstance(snap_ro, dict) else None

    brief = _build_brief(scan_ro, changes=changes)
    if not brief.strip():
        return {"text": "", "ops": []}

    # 只给 LLM 清洁会话视图：params/industry/turn/last_changes，去掉 raw_text 与内部字段
    # 这是上一轮「对账幻觉」根因：raw_text 含历史用户原文会诱导 LLM 翻历史猜
    clean_snap = {}
    if isinstance(snap_ro, dict):
        for k in ("params", "grouped_params", "params_summary",
                  "accepted_hypotheses", "industry", "turn", "last_changes"):
            if k in snap_ro:
                v = snap_ro[k]
                if k == "params" and isinstance(v, dict):
                    clean_snap[k] = {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                elif k == "grouped_params" and isinstance(v, dict):
                    # 分组视图：过滤掉下划线开头的内部键
                    clean_snap[k] = {
                        g: {kk: vv for kk, vv in gv.items() if not kk.startswith("_")}
                        for g, gv in v.items()
                    }
                else:
                    clean_snap[k] = v

    grounding = ""
    if clean_snap:
        try:
            grounding = "【当前会话状态（不含历史原文）】\n" + json.dumps(
                clean_snap, ensure_ascii=False
            ) + "\n\n"
        except (TypeError, ValueError):
            grounding = ""

    is_decision = _is_decision_scan(scan_ro)
    system = _SYSTEM_DECISION if is_decision else _SYSTEM
    if is_decision:
        user_prompt = (
            f"【用户原始输入】{user_text}\n\n"
            f"{grounding}"
            f"【结构化决策结果】\n{brief}\n\n"
            "请按系统提示词的「决策解说员」职责输出：客观数字 + 选项代价 + 反问用户底线。"
            "**严禁**出现倾向/命令/判决词（建议你/你应该/必须/别…），命中即违规。"
            "不必输出 ```ops 块；候选调整已由规则层给出。"
        )
    else:
        user_prompt = (
            f"【用户原始输入】{user_text}\n\n"
            f"{grounding}"
            f"【结构化分析结果】\n{brief}\n\n"
            "请基于以上给出解读与建议。若有需要编排的候选方案，按系统提示词输出 ```ops 块。"
        )
    # 主持人模式：根据 context 调整策略
    meta = {"asked_question": False, "made_recommendation": False}
    context = context or {}
    available_actions = context.get("available_actions", [])
    recommendation_count = context.get("recommendation_count", 0)
    missing_params = context.get("missing_params", [])
    has_default = context.get("has_default", {})

    # 构建主持人策略提示
    strategy_hints = []
    if missing_params:
        # 有缺失参数 -> 追问 1-2 个核心参数（补参永远优先，不受推荐计数限制）
        priority_params = [p for p in missing_params if p in (
            "monthly_rent", "daily_traffic", "price_per_unit",
            "employee_count", "avg_salary", "total_investment", "variable_cost_ratio",
        )]
        if not priority_params:
            priority_params = missing_params[:2]
        defaults_hint = ""
        for p in priority_params:
            if p in has_default:
                defaults_hint += f"- {p} 的默认值为 {has_default[p]}\n"
        strategy_hints.append(
            f"【追问】还缺以下核心参数：{', '.join(priority_params)}。"
            f"请追问这些参数（最多问 1-2 个），并告诉用户可以用默认值先算一下。\n"
            f"{defaults_hint}"
            f"示例：\"月租大概多少？没概念的话先用 8000 算一下。\""
        )
        meta["asked_question"] = True
    elif recommendation_count < 2 and available_actions:
        # 参数充足且推荐次数未满 -> 推荐一个动作
        # 排除「重新扫描(quick_scan)」与「对比(compare_scenarios)」，取第一个真正的下一步分析
        actionable = [a for a in available_actions if a not in ("quick_scan", "compare_scenarios")]
        pick = actionable[0] if actionable else "quick_scan"
        strategy_hints.append(
            f"【推荐】参数已充足。下一步最该看的是：{pick}。"
            f"结尾问\"要不要看看？\"，不要强推。"
        )
        meta["made_recommendation"] = True
    else:
        strategy_hints.append("【静默】不要推荐新动作，直接等用户指令。结尾说\"有什么想了解的直接说\"。")

    # 绝不分析的硬约束
    strategy_hints.append("【禁止分析】所有数字必须来自引擎输出。禁止自行做算术、推断趋势、评价参数好坏。只翻译数字含义和解释影响。")

    strategy_block = "\n\n".join(strategy_hints)

    try:
        resp = _get_llm().invoke([
            SystemMessage(content=system),
            HumanMessage(content=strategy_block + "\n\n" + user_prompt),
        ])
        raw_text = resp.content if isinstance(resp.content, str) else str(resp.content)
        raw_text = raw_text.strip()
        ops = _parse_ops(raw_text)
        # 从解读里剥除 ops 代码块（人不看 JSON）
        if ops:
            clean_text = _strip_ops_blocks(raw_text)
            return {"text": clean_text.strip(), "ops": ops, "meta": meta}
        return {"text": raw_text, "ops": [], "meta": meta}
    except Exception as e:  # noqa
        logger.warning(f"LLM 解读失败，跳过: {e}")
        return {"text": "", "ops": [], "meta": meta}


# ── ops 解析（```ops ... ```）─────────────────────────────────────────────

_OPS_BLOCK_RE = re.compile(r"```ops\s*\n(.*?)```", re.DOTALL)


def _parse_ops(text: str) -> list:
    """从 LLM 输出抽 ```ops 块并解析为 op 列表；解析失败返回 []。"""
    if not text:
        return []
    out: list = []
    for m in _OPS_BLOCK_RE.finditer(text):
        body = m.group(1).strip()
        try:
            ops = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning(f"ops 块 JSON 解析失败: {e}")
            continue
        if isinstance(ops, dict):
            out.append(ops)
        elif isinstance(ops, list):
            out.extend(ops)
    # 规整：确保每个 op 是 dict 且含 propose 字段
    return [o for o in out if isinstance(o, dict) and "propose" in o]


def _strip_ops_blocks(text: str) -> str:
    """从 LLM 文本里删 ```ops 块（人看的解读不展示 JSON 骨架）。"""
    return _OPS_BLOCK_RE.sub("", text)


# ── 模型配置读写（运行时切换，供 web_server /settings/llm 使用）──────────────

# 配置写锁：并发 POST 时串行化，避免两个请求同时写坏 config JSON
_config_write_lock = threading.Lock()


def _mask_key(key: str) -> str:
    """脱敏 API key：保留头尾各 4 位，中间打码。过短则整体打码。"""
    k = (key or "").strip()
    if len(k) <= 8:
        return "*" * len(k) if k else ""
    return f"{k[:4]}****{k[-4:]}"


def get_llm_config_view() -> dict:
    """给 /settings/llm 的脱敏配置视图：只回显掩码，绝不暴露完整 key。"""
    cfg = _load_llm_config().get("config", {})
    return {
        "model": cfg.get("model", "deepseek-v4-flash"),
        "base_url": cfg.get("base_url", DEEPSEEK_BASE_URL),
        "api_key_masked": _mask_key(cfg.get("api_key", "") or _api_key()),
        "llm_configured": has_api_key(),
    }


def save_llm_config(model: str, base_url: str, api_key: str) -> dict:
    """运行时保存模型配置到 agent_llm_config.json（原子写 + 锁）。

    - model / base_url 直接覆盖
    - api_key 为空字符串 → 不覆盖已存 key（允许只改名字/URL）
    - api_key 非空但 < 8 字符 → 抛 ValueError（前端已校验，后端双保险）
    - 保留 config 里其它字段（temperature/top_p/...）与顶层 sp/tools

    返回写入后的配置视图。
    """
    global _llm_cache
    with _config_write_lock:
        key_raw = (api_key or "").strip()
        if key_raw and len(key_raw) < 8:
            raise ValueError(f"API Key 过短（{len(key_raw)} 位），至少 8 位")

        path = _resolve_llm_config_path()
        # 基底：读现有文件（保留 sp/tools 等非 config 字段）
        try:
            with open(path, "r", encoding="utf-8") as f:
                full = json.load(f)
        except Exception:
            full = _load_llm_config()  # 文件缺失/损坏 → 用默认基底

        if not isinstance(full, dict):
            full = {}
        cfg = full.get("config") or {}
        if not isinstance(cfg, dict):
            cfg = {}
            full["config"] = cfg

        if model is not None and str(model).strip():
            cfg["model"] = str(model).strip()
        if base_url is not None and str(base_url).strip():
            cfg["base_url"] = str(base_url).strip()
        if key_raw:
            cfg["api_key"] = key_raw

        full["config"] = cfg

        # 原子写：临时文件 + os.replace，避免半截写入损坏配置
        tmp = None
        try:
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d or ".", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(full, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            tmp = None
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # 强制重建 LLM client（缓存失效；虽然 _get_llm 有签名比对，显式置 None 更保险）
    with _llm_cache_lock:
        _llm_cache = None

    return get_llm_config_view()


def test_llm_config(model: str, base_url: str, api_key: str) -> dict:
    """连通性探测：发一次最小请求验证 model+base_url+key 是否可用。

    返回：
    - {"ok": bool, "status_code": int|None, "error": str, "latency_ms": int}
    - 超时 5s，避免拖慢保存体验
    - 用 max_tokens=1 极简请求，几乎不消耗额度
    """
    import time as _time
    try:
        from requests import post, exceptions
    except ImportError:
        return {"ok": False, "status_code": None, "error": "requests 库不可用，跳过连通性探测", "latency_ms": 0}

    # 绕过代理：将 API 域名加入 NO_PROXY
    from urllib.parse import urlparse
    _parsed = urlparse(base_url)
    _domain = _parsed.hostname
    if _domain:
        for _var in ("NO_PROXY", "no_proxy"):
            _old = os.environ.get(_var, "")
            if _domain not in _old:
                os.environ[_var] = f"{_domain},{_old}" if _old else _domain

    url = (base_url or "").strip().rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {(api_key or '').strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": (model or "").strip(),
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }
    t0 = _time.time()
    try:
        resp = post(url, headers=headers, json=payload, timeout=5, verify=True)
        latency = int((_time.time() - t0) * 1000)
        if resp.status_code == 200:
            return {"ok": True, "status_code": 200, "error": "", "latency_ms": latency}
        return {"ok": False, "status_code": resp.status_code, "error": f"HTTP {resp.status_code}: {resp.text[:200]}", "latency_ms": latency}
    except exceptions.Timeout:
        latency = int((_time.time() - t0) * 1000)
        return {"ok": False, "status_code": None, "error": f"探测超时（>5s）", "latency_ms": latency}
    except exceptions.ConnectionError as e:
        latency = int((_time.time() - t0) * 1000)
        return {"ok": False, "status_code": None, "error": f"连接失败: {e}", "latency_ms": latency}
    except Exception as e:  # noqa: BLE001
        latency = int((_time.time() - t0) * 1000)
        return {"ok": False, "status_code": None, "error": f"探测异常: {e}", "latency_ms": latency}
