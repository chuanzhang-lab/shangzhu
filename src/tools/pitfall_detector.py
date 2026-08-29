"""
陷阱检测工具 — 创业者军师避坑引擎

内置创业常见硬伤规则库，覆盖定价、现金流、市场、团队、合规五大类。
自动触发检测，给出具体警告和可行对策。

设计说明：
- 核心逻辑提取为普通函数（_xxx），供 run_full_pitfall_scan 复用
- @tool 装饰的函数只做薄封装，调用对应的普通函数
- 避免 @tool 函数之间互相调用（会导致 'StructuredTool' object is not callable）
"""

import json
from typing import Optional
from langchain.tools import tool


# ─── 公共规则库 ──────────────────────────────────────────────────────────

INDUSTRY_COMPLIANCE_MAP = {
    "餐饮": ["食品经营许可证", "卫生许可证", "从业人员健康证", "消防验收"],
    "食品": ["食品经营许可证", "卫生许可证", "SC 生产许可证"],
    "医疗": ["医疗机构执业许可证", "医疗器械经营许可证", "医师执业证"],
    "药品": ["药品经营许可证", "GSP 认证"],
    "教育": ["办学许可证", "教师资格证"],
    "金融": ["金融许可证", "支付业务许可证", "基金销售牌照"],
    "保险": ["保险业务许可证"],
    "证券": ["证券业务许可证"],
    "房地产": ["房地产开发资质", "商品房预售许可证"],
    "游戏": ["网络文化经营许可证", "游戏版号", "ICP 许可证"],
    "直播": ["网络文化经营许可证", "ICP 许可证", "广播电视节目制作经营许可证"],
    "物流": ["道路运输经营许可证"],
    "酒店": ["特种行业许可证", "消防安全检查合格证"],
    "美容": ["卫生许可证", "医疗机构执业许可证（如有医美）"],
    "宠物": ["动物诊疗许可证（如有诊疗）", "动物防疫条件合格证"],
}


def _check_compliance_keywords(description: str) -> list[str]:
    """从项目描述中匹配行业合规关键词"""
    found = []
    for keyword, licenses in INDUSTRY_COMPLIANCE_MAP.items():
        if keyword in description:
            found.extend(licenses)
    return list(set(found))


# ─── 核心逻辑（普通函数，可被 tool 和 run_full_pitfall_scan 复用）─────────

def _do_pricing_check(
    price: float,
    variable_cost: float,
    competitor_price: Optional[float] = None,
    industry_avg_margin: Optional[float] = None,
) -> dict:
    """定价陷阱检测核心逻辑"""
    pitfalls = []
    suggestions = []
    severity = "low"

    if price <= variable_cost:
        pitfalls.append({
            "type": "定价低于成本",
            "severity": "critical",
            "detail": f"定价 {price} ≤ 变动成本 {variable_cost}，每卖一单都在亏损。",
            "impact": "卖得越多亏得越多，这是最常见的创业死亡原因之一。"
        })
        suggestions.append("立即将定价提高到变动成本的至少 1.5-2 倍。")
        severity = "critical"

    margin = (price - variable_cost) / price * 100 if price > 0 else 0
    if margin < 20:
        pitfalls.append({
            "type": "毛利率过低",
            "severity": "high",
            "detail": f"毛利率仅 {round(margin, 1)}%，扣除固定成本后可能没有利润。",
            "impact": "无法覆盖运营和获客成本，难以持续。"
        })
        suggestions.append(f"目标毛利率至少 40-50%，当前需将价格提高到约 {round(variable_cost / 0.5, 2)} 或降低变动成本。")
        if severity != "critical":
            severity = "high"

    if competitor_price and price < competitor_price * 0.5:
        pitfalls.append({
            "type": "价格远低于竞品",
            "severity": "medium",
            "detail": f"定价 {price} 不到竞品价格 {competitor_price} 的 50%。",
            "impact": "可能引发价格战，或让用户怀疑质量。低价不等于竞争力。"
        })
        suggestions.append("考虑差异化定位而非单纯低价竞争。如果成本结构确实更低，确保这个优势是可持续的。")

    if industry_avg_margin and margin < industry_avg_margin * 0.7:
        pitfalls.append({
            "type": "毛利率低于行业均值",
            "severity": "medium",
            "detail": f"毛利率 {round(margin, 1)}% 远低于行业平均 {industry_avg_margin}%。",
            "impact": "可能在商业模式或成本控制上存在结构性问题。"
        })
        suggestions.append("分析成本结构，找出与行业差距的根源。")

    result = {
        "analyzed": {"price": price, "variable_cost": variable_cost, "gross_margin": f"{round(margin, 1)}%"},
        "pitfall_count": len(pitfalls),
        "severity": severity,
        "pitfalls": pitfalls,
        "suggestions": suggestions,
    }
    if not pitfalls:
        result["message"] = "未检测到明显的定价陷阱，定价策略基本合理。"
    return result


def _do_cashflow_check(
    current_cash: float,
    monthly_expense: float,
    monthly_revenue: float = 0,
    accounts_receivable_days: float = 0,
    accounts_payable_days: float = 0,
    inventory_turnover_days: float = 0,
) -> dict:
    """现金流陷阱检测核心逻辑"""
    pitfalls = []
    suggestions = []
    severity = "low"

    net_burn = (monthly_expense or 0) - (monthly_revenue or 0)
    current_cash = current_cash if current_cash is not None else 0
    if net_burn > 0:
        runway = current_cash / net_burn
        if runway < 6:
            pitfalls.append({
                "type": "现金流即将断裂",
                "severity": "critical",
                "detail": f"现金仅能支撑 {round(runway, 1)} 个月。",
                "impact": "资金链断裂是创业公司第一大死因。"
            })
            suggestions.append("立即削减非必要支出；加速应收账款回收；启动融资或寻求过桥贷款。")
            severity = "critical"
        elif runway < 12:
            pitfalls.append({
                "type": "现金流偏紧",
                "severity": "high",
                "detail": f"现金仅能支撑 {round(runway, 1)} 个月，不足一年。",
                "impact": "留给试错和调整的时间窗口很窄。"
            })
            suggestions.append("制定 3 个月内降本 20% 的计划；提前接触投资人。")
            if severity != "critical":
                severity = "high"

    if accounts_receivable_days > 0 and accounts_payable_days > 0:
        gap = accounts_receivable_days - accounts_payable_days
        if gap > 30:
            pitfalls.append({
                "type": "现金流剪刀差",
                "severity": "high",
                "detail": f"应收账款 {accounts_receivable_days} 天，应付账款 {accounts_payable_days} 天，存在 {round(gap)} 天资金缺口。",
                "impact": "你在用自己的钱帮客户垫资。"
            })
            suggestions.append(f"缩短账期目标：将应收账款压缩到 {round(accounts_payable_days)} 天以内；对大客户要求预付。")

    if inventory_turnover_days > 90:
        pitfalls.append({
            "type": "存货周转过慢",
            "severity": "medium",
            "detail": f"存货周转天数 {inventory_turnover_days} 天，超过 3 个月。",
            "impact": "大量资金沉淀在库存中，且面临贬值/过期风险。"
        })
        suggestions.append("清理滞销库存；优化采购策略；考虑 JIT 或预售模式。")

    if monthly_revenue == 0 and monthly_expense > 0:
        pitfalls.append({
            "type": "零收入持续消耗",
            "severity": "high",
            "detail": "目前没有任何收入，但每月固定支出持续。",
            "impact": "如果不能在跑道耗尽前实现收入，项目将被迫终止。"
        })
        suggestions.append("设定明确的收入里程碑和截止日期；考虑先做最小可行产品（MVP）快速验证。")
        if severity != "critical":
            severity = "high"

    result = {
        "analyzed": {
            "current_cash": current_cash,
            "monthly_expense": monthly_expense,
            "monthly_revenue": monthly_revenue,
            "net_monthly_burn": round(net_burn, 2),
            "runway_months": round(current_cash / net_burn, 1) if net_burn > 0 else "无限",
        },
        "pitfall_count": len(pitfalls),
        "severity": severity,
        "pitfalls": pitfalls,
        "suggestions": suggestions,
    }
    if not pitfalls:
        result["message"] = "未检测到明显的现金流陷阱，现金流状况基本健康。"
    return result


def _do_market_check(
    tam_description: str,
    team_size: int,
    has_competitor: bool = True,
    customer_concentration: Optional[float] = None,
    description: str = "",
) -> dict:
    """市场陷阱检测核心逻辑"""
    pitfalls = []
    suggestions = []
    severity = "low"

    huge_market_keywords = ["万亿", "千亿", "所有人", "全部", "任何人", "全民", "全球"]
    is_huge = any(kw in tam_description for kw in huge_market_keywords)
    if is_huge and team_size < 20:
        pitfalls.append({
            "type": "市场定义过宽",
            "severity": "medium",
            "detail": f"TAM 描述使用了宽泛词汇，但团队仅 {team_size} 人。",
            "impact": "过于宽泛的市场定义意味着没有明确的切入点，资源会被分散。"
        })
        suggestions.append("将市场缩小到可验证的细分领域。问自己：'前 100 个付费用户具体是谁？'")

    no_competitor_signals = ["没有竞争", "没有对手", "无竞争", "蓝海", "空白市场", "独一无二"]
    if not has_competitor or any(sig in description for sig in no_competitor_signals):
        pitfalls.append({
            "type": "声称无竞争对手",
            "severity": "high",
            "detail": "声称或暗示没有竞争对手。",
            "impact": "几乎不存在真正的'无人区'。'无竞争'通常意味着：市场不存在、你不知道竞品、或替代方案你没识别。"
        })
        suggestions.append("认真回答：用户目前用什么方式解决这个问题？那才是真正的竞争对手。")

    if customer_concentration is not None and customer_concentration > 40:
        pitfalls.append({
            "type": "单一客户依赖",
            "severity": "high",
            "detail": f"最大客户收入占比 {customer_concentration}%，超过 40% 红线。",
            "impact": "失去这一个客户可能导致公司现金流断裂。"
        })
        suggestions.append(f"目标是将最大客户占比降到 30% 以下。积极拓展新客户分散风险。")

    result = {
        "analyzed": {
            "tam_description": tam_description[:100],
            "team_size": team_size,
            "has_competitor": has_competitor,
            "customer_concentration": f"{customer_concentration}%" if customer_concentration else "未提供",
        },
        "pitfall_count": len(pitfalls),
        "severity": severity,
        "pitfalls": pitfalls,
        "suggestions": suggestions,
    }
    if not pitfalls:
        result["message"] = "未检测到明显的市场陷阱。"
    return result


def _do_team_check(
    founder_count: int,
    has_tech_cofounder: bool = True,
    is_tech_project: bool = False,
    has_domain_expert: bool = True,
    industry: str = "",
) -> dict:
    """团队陷阱检测核心逻辑"""
    pitfalls = []
    suggestions = []
    # 无默认值：创始人信息缺失（None）→ 不虚构团队结构，返回空结果。
    if founder_count is None:
        return {
            "analyzed": {"founder_count": None, "has_tech_cofounder": has_tech_cofounder,
                         "is_tech_project": is_tech_project, "has_domain_expert": has_domain_expert},
            "pitfall_count": 0, "severity": "low",
            "pitfalls": [], "suggestions": [],
            "message": "团队信息未提供，跳过团队陷阱扫描。",
        }
    severity = "low"

    if founder_count < 2:
        pitfalls.append({
            "type": "单一创始人",
            "severity": "high",
            "detail": "只有一位创始人。",
            "impact": "所有决策压力集中在一个人身上，缺乏制衡和互补。投资人对单一创始人团队通常更谨慎。"
        })
        suggestions.append("尽快找到 1-2 位互补的联合创始人，覆盖技术/产品/市场中的薄弱环节。")

    if is_tech_project and not has_tech_cofounder:
        pitfalls.append({
            "type": "技术项目缺少技术合伙人",
            "severity": "critical",
            "detail": "这是一个技术驱动型项目，但团队中缺少技术合伙人。",
            "impact": "技术决策、产品迭代、团队招聘都会受到严重影响。外包技术团队很难做出好产品。"
        })
        suggestions.append("必须找到一位技术合伙人（CTO），而非依赖外包。核心技术和产品必须掌握在团队内部。")
        severity = "critical"

    if not has_domain_expert:
        pitfalls.append({
            "type": "缺乏行业专家",
            "severity": "medium",
            "detail": "团队中缺少对目标行业有深入理解的人。",
            "impact": "可能做出'技术很好但没人需要'的产品，或踩到行业特有的坑。"
        })
        suggestions.append("引入一位有行业经验的顾问或合伙人，至少在早期阶段深度参与。")

    result = {
        "analyzed": {
            "founder_count": founder_count,
            "has_tech_cofounder": has_tech_cofounder,
            "is_tech_project": is_tech_project,
            "has_domain_expert": has_domain_expert,
        },
        "pitfall_count": len(pitfalls),
        "severity": severity,
        "pitfalls": pitfalls,
        "suggestions": suggestions,
    }
    if not pitfalls:
        result["message"] = "未检测到明显的团队陷阱，团队结构基本合理。"
    return result


def _do_compliance_check(project_description: str, industry: str = "") -> dict:
    """合规陷阱检测核心逻辑"""
    text = project_description + industry
    licenses = _check_compliance_keywords(text)

    result = {
        "analyzed_industry_keywords": [kw for kw in INDUSTRY_COMPLIANCE_MAP if kw in text],
        "required_licenses": licenses,
        "pitfall_count": len(licenses),
    }

    if licenses:
        result["severity"] = "high"
        result["warning"] = f"检测到 {len(licenses)} 项可能的合规要求，遗漏任何一项都可能导致罚款或停业。"
        result["suggestion"] = "建议在正式运营前咨询专业律师或工商代办，确认完整的许可证清单。"
    else:
        result["severity"] = "low"
        result["message"] = "未从描述中识别到特殊行业合规要求。如涉及食品、医疗、金融、教育等领域，请自行核实。"
        result["suggestion"] = "所有行业至少需要：营业执照、税务登记、社保登记。"

    return result


# ─── @tool 薄封装（每个 tool 调用对应的 _do_xxx 函数）────────────────────


@tool
def detect_pricing_pitfalls(
    price: float,
    variable_cost: float,
    competitor_price: Optional[float] = None,
    industry_avg_margin: Optional[float] = None,
) -> str:
    """检测定价陷阱。参数: price(定价), variable_cost(变动成本), competitor_price(竞品价格,可选), industry_avg_margin(行业平均毛利率%,可选)"""
    return json.dumps(_do_pricing_check(price, variable_cost, competitor_price, industry_avg_margin), ensure_ascii=False, indent=2)


@tool
def detect_cashflow_pitfalls(
    current_cash: float,
    monthly_expense: float,
    monthly_revenue: float = 0,
    accounts_receivable_days: float = 0,
    accounts_payable_days: float = 0,
    inventory_turnover_days: float = 0,
) -> str:
    """检测现金流陷阱。参数: current_cash(现金余额), monthly_expense(月支出), monthly_revenue(月收入), accounts_receivable_days, accounts_payable_days, inventory_turnover_days"""
    return json.dumps(_do_cashflow_check(current_cash, monthly_expense, monthly_revenue, accounts_receivable_days, accounts_payable_days, inventory_turnover_days), ensure_ascii=False, indent=2)


@tool
def detect_market_pitfalls(
    tam_description: str,
    team_size: int,
    has_competitor: bool = True,
    customer_concentration: Optional[float] = None,
    description: str = "",
) -> str:
    """检测市场陷阱。参数: tam_description(TAM描述), team_size(团队人数), has_competitor, customer_concentration(最大客户占比%), description(项目描述)"""
    return json.dumps(_do_market_check(tam_description, team_size, has_competitor, customer_concentration, description), ensure_ascii=False, indent=2)


@tool
def detect_team_pitfalls(
    founder_count: int,
    has_tech_cofounder: bool = True,
    is_tech_project: bool = False,
    has_domain_expert: bool = True,
    industry: str = "",
) -> str:
    """检测团队陷阱。参数: founder_count(创始人数量), has_tech_cofounder, is_tech_project, has_domain_expert, industry"""
    return json.dumps(_do_team_check(founder_count, has_tech_cofounder, is_tech_project, has_domain_expert, industry), ensure_ascii=False, indent=2)


@tool
def detect_compliance_pitfalls(project_description: str, industry: str = "") -> str:
    """检测合规陷阱。参数: project_description(项目描述), industry(行业)"""
    return json.dumps(_do_compliance_check(project_description, industry), ensure_ascii=False, indent=2)


@tool
def run_full_pitfall_scan(
    price: Optional[float] = None,
    variable_cost: Optional[float] = None,
    current_cash: Optional[float] = None,
    monthly_expense: Optional[float] = None,
    monthly_revenue: float = 0,
    team_size: int = 1,
    founder_count: int = 1,
    has_tech_cofounder: bool = True,
    is_tech_project: bool = False,
    has_domain_expert: bool = True,
    project_description: str = "",
    industry: str = "",
    tam_description: str = "",
    customer_concentration: Optional[float] = None,
) -> str:
    """
    一键全维度陷阱扫描。传入所有已知参数，自动检测所有维度的陷阱。

    这会让 Agent 在分析任何项目时都能自动检测所有维度的陷阱，
    无需逐个调用上述单个检测工具。
    """
    all_pitfalls = []
    all_suggestions = []
    total_count = 0
    max_severity = "low"

    severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    def _update(result_dict: dict, category: str):
        nonlocal total_count, max_severity
        if "pitfalls" in result_dict and result_dict["pitfalls"]:
            for p in result_dict["pitfalls"]:
                p["category"] = category
                all_pitfalls.append(p)
                total_count += 1
        if "suggestions" in result_dict and result_dict["suggestions"]:
            all_suggestions.extend(result_dict["suggestions"])
        if result_dict.get("severity", "low") in severity_order:
            if severity_order[result_dict["severity"]] > severity_order[max_severity]:
                max_severity = result_dict["severity"]

    # 调用普通函数（而非 @tool 函数），避免 'StructuredTool' object is not callable
    if price is not None and variable_cost is not None:
        _update(_do_pricing_check(price=price, variable_cost=variable_cost), "定价")

    if current_cash is not None and monthly_expense is not None:
        _update(_do_cashflow_check(current_cash=current_cash, monthly_expense=monthly_expense, monthly_revenue=monthly_revenue), "现金流")

    if tam_description:
        _update(_do_market_check(tam_description=tam_description, team_size=team_size, customer_concentration=customer_concentration, description=project_description), "市场")

    _update(_do_team_check(founder_count=founder_count, has_tech_cofounder=has_tech_cofounder, is_tech_project=is_tech_project, has_domain_expert=has_domain_expert, industry=industry), "团队")

    if project_description or industry:
        _update(_do_compliance_check(project_description, industry), "合规")

    result = {
        "total_pitfalls": total_count,
        "overall_severity": max_severity,
        "pitfalls_by_category": {},
    }

    for p in all_pitfalls:
        cat = p.pop("category", "其他")
        if cat not in result["pitfalls_by_category"]:
            result["pitfalls_by_category"][cat] = []
        result["pitfalls_by_category"][cat].append(p)

    if all_suggestions:
        result["action_items"] = all_suggestions[:5]

    if total_count == 0:
        result["message"] = "未检测到明显陷阱。但建议持续关注：现金流变化、竞争格局、合规要求更新。"

    return json.dumps(result, ensure_ascii=False, indent=2)


# ─── 纯函数版本（供 Workflow Engine 调用，返回 dict）─────────────────────

def _do_full_scan(
    price: Optional[float] = None,
    variable_cost: Optional[float] = None,
    current_cash: Optional[float] = None,
    monthly_expense: Optional[float] = None,
    monthly_revenue: float = 0,
    team_size: int = 1,
    founder_count: int = 1,
    has_tech_cofounder: bool = True,
    is_tech_project: bool = False,
    has_domain_expert: bool = True,
    project_description: str = "",
    industry: str = "",
    tam_description: str = "",
    customer_concentration: Optional[float] = None,
) -> dict:
    """纯函数版本的全维度陷阱扫描，返回 dict（而非 JSON 字符串）"""
    all_pitfalls = []
    all_suggestions = []
    total_count = 0
    max_severity = "low"
    severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    def _update(result_dict: dict, category: str):
        nonlocal total_count, max_severity
        if "pitfalls" in result_dict and result_dict["pitfalls"]:
            for p in result_dict["pitfalls"]:
                p["category"] = category
                all_pitfalls.append(p)
                total_count += 1
        if "suggestions" in result_dict and result_dict["suggestions"]:
            all_suggestions.extend(result_dict["suggestions"])
        if result_dict.get("severity", "low") in severity_order:
            if severity_order[result_dict["severity"]] > severity_order[max_severity]:
                max_severity = result_dict["severity"]

    if price is not None and variable_cost is not None:
        _update(_do_pricing_check(price=price, variable_cost=variable_cost), "定价")

    if current_cash is not None and monthly_expense is not None:
        _update(_do_cashflow_check(current_cash=current_cash, monthly_expense=monthly_expense, monthly_revenue=monthly_revenue), "现金流")

    if tam_description:
        _update(_do_market_check(tam_description=tam_description, team_size=team_size, customer_concentration=customer_concentration, description=project_description), "市场")

    _update(_do_team_check(founder_count=founder_count, has_tech_cofounder=has_tech_cofounder, is_tech_project=is_tech_project, has_domain_expert=has_domain_expert, industry=industry), "团队")

    if project_description or industry:
        _update(_do_compliance_check(project_description, industry), "合规")

    result = {
        "total_pitfalls": total_count,
        "overall_severity": max_severity,
        "pitfalls_by_category": {},
    }

    for p in all_pitfalls:
        cat = p.pop("category", "其他")
        if cat not in result["pitfalls_by_category"]:
            result["pitfalls_by_category"][cat] = []
        result["pitfalls_by_category"][cat].append(p)

    if all_suggestions:
        result["action_items"] = all_suggestions[:5]

    if total_count == 0:
        result["message"] = "未检测到明显陷阱。"

    return result
