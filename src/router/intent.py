"""意图路由器 — 不调 LLM 的纯规则路由

9 类意图，按关键词/正则匹配：
- quick_scan: 描述项目 / 改参数
- trend: 趋势/预测/未来/走势
- compare: 对比/A vs B/如果
- suggest: 怎么调/扭亏/建议改
- report_pdf: 生成PDF
- report_excel: 生成Excel
- benchmark: 行业基准/数据
- market: 市场调研/竞品
- chitchat: 兜底（走 LLM）

匹配顺序：先匹配更具体的（suggest/compare/report），后匹配宽泛的（quick_scan/chitchat）。
多意图：按句号/问号切分输入，每段独立判意图，取最具体的非 chitchat 段为主意图。
"""

import re
from typing import Tuple, Optional, List


# ─── 意图规则 ──────────────────────────────────────────────────────────────
# 每条规则: (intent_name, [keyword_list], [regex_list])
# 命中其中任一关键词或正则即匹配

_RULES = [
    # 报告生成（优先匹配，避免被 "PDF" 散落词污染）
    (
        "report_pdf",
        ["生成pdf", "生成报告", "导出pdf", "下载pdf", "pdf报告", "出pdf", "给个pdf",
         "生成PDF", "导出PDF", "下载PDF", "PDF报告", "出PDF", "给个PDF"],
        [r"pdf\s*报告", r"出\s*pdf", r"导出.*pdf", r"PDF\s*报告", r"出\s*PDF", r"导出.*PDF"],
    ),
    (
        "report_excel",
        ["生成excel", "导出excel", "下载excel", "excel模型", "出excel", "给个excel", "表格模型",
         "生成Excel", "导出Excel", "下载Excel", "Excel模型", "出Excel", "给个Excel", "表格模型"],
        [r"excel\s*模型", r"出\s*excel", r"Excel\s*模型", r"出\s*Excel", r"导出.*Excel"],
    ),
    # 调参建议（具体，优先）
    (
        "suggest",
        [
            "怎么调", "如何调", "怎么扭亏", "如何扭亏", "扭亏为盈",
            "建议改", "建议调", "怎么改", "如何改", "改成什么", "改多少",
            "调什么", "调多少", "改什么",
            "参数建议", "参数优化", "调整建议", "调整方案", "改进方向",
            "调参", "怎么优化", "如何优化", "怎么改好", "如何改进",
            "扭亏", "如何救活", "怎么救活",
        ],
        [],
    ),
    # 对比
    (
        "compare",
        [
            "对比", "比较", " vs ", "vs.", "两种方案", "两个方案",
            "选哪个", "选a", "选b", "方案a", "方案b",
            "如果", "假如", "假设", "要是",
            # P4-3 what-if 选择类：让「减租好还是提价好」等归引擎 compare
            "好还是", "还是好", "哪个更好", "怎么选", "选哪个好",
            "更划算", "哪个划算", "a还是b", "还是", "哪个好",
        ],
        [r"\bvs\.?\b", r"方案\s*[abAB]", r"\bif\b", r"如果.*会",
         # P4-3 what-if 选择问句：「X好，还是Y好」「减租还是提价」归引擎 compare
         r"好\s*[，,]?\s*还是", r"还是\s*[^，。？！]*好[\？?]?$"],
    ),
    # 保本 / 收支平衡（P4-3：归引擎 quick_scan 计算 breakeven，不落 chitchat/自由 agent）
    (
        "breakeven",
        ["保本", "不亏", "盈亏平衡", "收支平衡", "多少能平", "打平", "持平", "盈亏点", "不亏本"],
        [r"保本", r"收支平衡", r"盈亏平衡", r"打平", r"持平", r"多少.*平"],
    ),
    # 趋势
    (
        "trend",
        [
            "趋势", "预测", "未来", "走势", "未来12个月", "下个月",
            "12个月", "一年走势", "回本时间", "回本", "现金流走势",
            "几个月回本", "多久回本", "什么时候盈利",
        ],
        [r"\d+\s*个?月", r"未来\s*\d+\s*个?月", r"趋势", r"预测", r"回本"],
    ),
    # L2 决策（验证期决策工作台）：该不该开/继续/先验证/撑多久→decide
    # （怎么扭亏/调参已归 suggest，此处只收决策类问句；决策类型由 decide 子路由细分）
    (
        "decide",
        [
            "该不该开", "要不要开", "能不能开", "值得开吗", "值得开", "该开吗",
            "该不该继续", "要不要继续", "能不能继续", "该继续吗", "要不要撤",
            "要不要停", "关不关", "该不该关", "要不要关", "继续下去", "还行不行",
            "先验证什么", "先验证哪", "验证什么", "先做什么",
            "能撑多久", "撑多久", "能扛多久", "资金够撑", "现金够撑", "还能撑",
            "划不划算", "值不值", "要不要做", "该不该做", "能不能做",
        ],
        [r"该不该", r"要不要", r"能不能", r"撑多久", r"先验证", r"值不值得"],
    ),
    # 现金流明细（档 B）：钱什么时候花完/现金流怎样/钱够不够 → cashflow（明细表）
    # 「撑多久/还能撑」归上面 decide/runway（决策）；此处收「现金流/明细/月底钱」类
    (
        "cashflow",
        [
            "现金流", "现金流水", "钱什么时候花完", "钱够不够", "缺多少钱", "还差多少钱",
            "一个月花多少", "每月支出", "现金明细", "现金流明细", "现金流怎么样",
            "资金够不够", "现金够不够", "钱够吗", "月底还有多少", "月底剩多少", "现金到几月",
        ],
        [r"现金流", r"(?:现金|资金|钱).*(?:够|缺|花完|到几月)", r"月度现金"],
    ),
    # 成本归因拆解（为什么亏 / 钱花在哪 / 成本结构）
    (
        "attribution",
        [
            "为什么亏", "为什么亏损", "亏在哪", "钱花在哪", "钱都花哪了",
            "成本结构", "成本拆解", "成本归因", "成本分析", "成本占比",
            "钱去哪了", "花在哪", "花在哪儿", "主要成本", "大头在哪",
            "归因", "拆解成本", "成本明细",
        ],
        [r"为什么.*亏", r"钱.*花.*哪", r"成本.*(?:结构|拆解|归因|占比|分析)",
         r"(?:花|用).*在哪", r"(?:主要|最大).*成本"],
    ),
    # 敏感度分析（弹性 / 跌多少会亏 / 盈亏平衡点）
    (
        "sensitivity",
        [
            "敏感度", "敏感性", "弹性分析", "弹性",
            "跌多少会亏", "跌多少才亏", "降多少会亏",
            "涨多少才赚", "涨多少能赚",
            "客流跌到多少", "客流降到多少", "客流多少才不亏",
            "租金涨到多少", "租金多少会亏",
            "盈亏平衡点", "保本点", "平衡点",
        ],
        [r"(?:跌|降|少).*多少.*(?:亏|赚)", r"(?:涨|多).*多少.*(?:亏|赚)",
         r"敏感[度性]", r"弹性", r"盈亏平衡"],
    ),
    # 行业基准
    (
        "benchmark",
        [
            "行业基准", "行业数据", "行业平均", "行业指标",
            "benchmark", "参考值", "合理值", "行业标准",
            "竞品数据", "行业毛利率", "行业净利率", "行业获客成本",
            "行业增长率", "行业回本周期", "行业客单价",
        ],
        [r"行业\s*基准", r"行业\s*平均", r"行业\s*数据", r"行业\s*毛利率", r"行业\s*净利率",
         r"行业\s*获客成本", r"行业\s*增长率", r"行业\s*回本周期", r"行业\s*客单价"],
    ),
    # 市场调研
    (
        "market",
        [
            "市场调研", "市场分析", "市场规模", "市场前景",
            "用户调研", "目标用户", "用户画像",
            "竞品分析", "竞品调研", "竞争对手",
        ],
        [r"市场\s*(调研|分析|规模|前景)", r"竞品\s*(分析|调研)"],
    ),
    # 描述项目/改参数（最宽泛，最后匹配）
    (
        "quick_scan",
        [
            "开一家", "开一个", "做个", "做一个",
            "总投资", "月租", "员工", "客流", "客单价", "单价",
            "调整参数", "改参数", "更新参数", "重新算", "再算一次",
            # Phase 3：续算/修改意图——确保「再算一下/改一下/补充」也走引擎
            # 而非落 chitchat，否则跨轮 merge 不触发、反复报「信息不全」。
            "再算", "重算", "再分析", "重新分析", "改一下", "调整",
            "补充", "加上", "加一下",
            "现在", "当前", "我的项目",
        ],
        [r"开\s*[一]?[个家]?\s*[\u4e00-\u9fa5A-Za-z]+店"],
    ),
]


# 意图优先级（数字越大越优先）
_INTENT_PRIORITY = {
    "report_pdf": 100,
    "report_excel": 100,
    "decide": 85,
    "suggest": 80,
    "cashflow": 78,
    "compare": 70,
    "breakeven": 75,
    "attribution": 72,
    "sensitivity": 68,
    "trend": 60,
    "benchmark": 50,
    "market": 50,
    "quick_scan": 10,
    "chitchat": 0,
}


# 核心「数值型」项目字段——命中任一即视为「用户在供给/修改参数」。
# 注意：不含 industry（纯行业词如「餐饮」不应强制走 quick_scan，否则会
# 劫持 benchmark/market 类提问）。仅数值字段才强制作重算。
_CORE_PARAM_FIELDS = {
    "monthly_revenue", "monthly_rent", "total_investment", "price_per_unit",
    "daily_traffic", "employee_count", "avg_salary", "monthly_expense",
    "variable_cost_rate", "variable_cost_ratio", "founder_count", "city",
}


def _looks_like_param_update(text: str) -> bool:
    """文本是否携带了核心项目数值参数。

    用于兜底：当用户只说「月营收20000元」「月租金8000元」这类纯补参句子时，
    关键词路由会误判为 chitchat，导致该轮不写 SessionState、跨轮累积断裂。
    命中核心数值字段则强制走 quick_scan。
    """
    try:
        from router.param_extractor import extract_params
    except Exception:  # pragma: no cover - 极端导入失败
        return False
    try:
        p = extract_params(text)
    except Exception:  # pragma: no cover
        return False
    if any(f in p for f in _CORE_PARAM_FIELDS):
        return True
    # 守门层拦截/修正过参数（如「6000%」）也视为参数更新，让 quick_scan 渲染确认横幅，
    # 而不是落入 chitchat 把「请确认」信号吞掉
    g = p.get("_guard") if isinstance(p, dict) else None
    if isinstance(g, dict) and (g.get("needs_confirmation") or g.get("issues")):
        return True
    return False


def _finalize(intent: str, score: float, text: str) -> Tuple[str, float]:
    """最终意图裁定（含兜底）。

    Phase 3 修复：纯 chitchat 但文本含核心项目参数时，强制走 quick_scan，
    让引擎基于 SessionState 合并后的参数重算，避免跨轮累积的参数被「闲聊」
    路径吞掉而丢失。

    L2 决策：文本含强决策问句（该不该/要不要开或续/先验证/撑多久/值不值）时，
    即使夹带参数描述也应归 decide，让规则层给「选项+风险+验证」而非纯仪表盘。
    """
    if intent == "chitchat" and _looks_like_param_update(text):
        return ("quick_scan", max(score, 0.9))
    if intent in ("quick_scan", "chitchat") and _looks_like_decision_question(text):
        return ("decide", max(score, 0.9))
    if intent in ("quick_scan", "chitchat") and _looks_like_cashflow_question(text):
        return ("cashflow", max(score, 0.9))
    return (intent, score)


_DECISION_MARKERS = (
    "该不该开", "要不要开", "能不能开", "值得开", "该开吗",
    "该不该继续", "要不要继续", "能不能继续", "该继续吗",
    "要不要撤", "要不要停", "关不关", "该不该关", "要不要关",
    "继续下去", "还行不行", "先验证什么", "先验证哪", "验证什么",
    "撑多久", "能扛多久", "资金够撑", "现金够撑", "还能撑",
    "划不划算", "值不值", "要不要做", "该不该做", "能不能做",
)


def _looks_like_decision_question(text: str) -> bool:
    """文本是否含 L2 决策问句（夹带参数也应路由 decide）。"""
    return any(m in text for m in _DECISION_MARKERS)


_CASHFLOW_MARKERS = (
    "现金流", "现金流水", "钱什么时候花完", "钱够不够", "钱够吗",
    "缺多少钱", "还差多少钱", "现金够不够", "资金够不够",
    "月底还有多少", "月底剩多少", "现金到几月", "现金流明细",
    "现金明细", "月度现金",
)


def _looks_like_cashflow_question(text: str) -> bool:
    """文本是否含现金流明细问句（夹带参数也应路由 cashflow；「撑多久」归 decide）。"""
    return any(m in text for m in _CASHFLOW_MARKERS)


def _split_clauses(text: str) -> List[str]:
    """按句末标点切分文本为多个子句"""
    # 按 . ? ! 。？！ 切分
    parts = re.split(r"[。.？！?!;；\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def _score_intent(text: str) -> Tuple[str, float]:
    """对单段文本判意图，返回 (intent, score)"""
    if not text or not text.strip():
        return ("chitchat", 0.0)

    text_lower = text.lower()
    matches = []

    for intent, keywords, regexes in _RULES:
        score = 0.0
        for kw in keywords:
            if kw in text or kw in text_lower:
                score += 1.0
            elif kw.lower() in text_lower:
                score += 0.8
        for rgx in regexes:
            if re.search(rgx, text, re.IGNORECASE):
                score += 1.5
        if score > 0:
            matches.append((intent, score))

    if not matches:
        return ("chitchat", 0.0)

    matches.sort(key=lambda x: -x[1])
    return matches[0]


def detect_intent(text: str) -> Tuple[str, float]:
    """
    检测用户输入的意图。
    多子句时按"优先级最高的非 chitchat 子句"选主意图。

    返回 (intent_name, score)。
    """
    if not text or not text.strip():
        return ("chitchat", 0.0)

    # 多子句: 按优先级选最具体的
    clauses = _split_clauses(text)
    if len(clauses) > 1:
        # 每段判意图，按 priority 排序
        scored = []
        for clause in clauses:
            intent, score = _score_intent(clause)
            scored.append((intent, score))
        # 按 priority 降序
        scored.sort(key=lambda x: -_INTENT_PRIORITY.get(x[0], 0))
        # 取第一个非 chitchat
        for intent, score in scored:
            if intent != "chitchat":
                return _finalize(intent, score, text)
        intent, score = (scored[0] if scored else ("chitchat", 0.0))
        return _finalize(intent, score, text)

    # 单子句
    intent, score = _score_intent(text)
    return _finalize(intent, score, text)


def detect_intent_safe(text: str) -> str:
    """便捷版本：只返回意图名。"""
    intent, _ = detect_intent(text)
    return intent


def decide_type_of(text: str) -> str:
    """从决策类问句提取 L2 决策类型（供 web_server 子路由）。

    返回 turnaround / validate_first / go_no_go / continue_stop / runway / choose。
    兜底：无法归类时给 turnaround（默认高频）。
    """
    if not text:
        return "turnaround"
    t = text.strip()
    # 怎么扭亏/怎么救/调整方向 → turnaround（note: 这类通常走 suggest，兜底在这）
    if any(k in t for k in ("扭亏", "救活", "怎么改", "怎么调", "怎么优化", "改什么")):
        return "turnaround"
    if any(k in t for k in ("先验证", "验证什么", "验证哪")):
        return "validate_first"
    if any(k in t for k in ("该不该开", "要不要开", "能不能开", "值得开", "该开吗",
                            "划不划算", "值不值", "要不要做", "该不该做", "能不能做")):
        return "go_no_go"
    if any(k in t for k in ("该不该继续", "要不要继续", "能不能继续", "该继续吗",
                            "要不要撤", "要不要停", "关不关", "该不该关", "要不要关",
                            "继续下去", "还行不行")):
        return "continue_stop"
    if any(k in t for k in ("撑多久", "能扛多久", "资金够撑", "现金够撑", "还能撑")):
        return "runway"
    if any(k in t for k in ("选哪个", "好还是", "哪个好", "怎么选", "还是", "对比")):
        return "choose"
    return "turnaround"
