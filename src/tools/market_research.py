"""
联网搜索工具 — 市场调研与竞品分析

使用 coze-coding-dev-sdk 的 SearchClient 进行联网搜索，
获取行业数据、竞品信息、市场趋势等实时信息。
Coze SDK 不可用时返回提示信息。
"""

import json
from langchain.tools import tool

# 尝试导入 Coze SDK，不可用时设为 None
try:
    from coze_coding_dev_sdk import SearchClient
    from coze_coding_utils.runtime_ctx.context import new_context
    from coze_coding_utils.log.write_log import request_context
    _HAS_COZE_SDK = True
except ImportError:
    SearchClient = None
    _HAS_COZE_SDK = False


def _get_context():
    """获取请求上下文，Coze 不可用时返回 None"""
    if not _HAS_COZE_SDK:
        return None
    try:
        return request_context.get() or new_context(method="search")
    except Exception:
        return None


def _search_with_coze(query: str, count: int = 5):
    """使用 Coze SDK 搜索"""
    ctx = _get_context()
    client = SearchClient(ctx=ctx)
    return client.web_search_with_summary(query=query, count=min(count, 10))


def _format_results(response, query: str) -> str:
    """格式化搜索结果"""
    results = []
    if response.web_items:
        for item in response.web_items:
            results.append({
                "title": item.title or "",
                "url": item.url or "",
                "snippet": (item.snippet or "")[:300],
                "source": item.site_name or "",
                "authority": item.auth_info_des or "",
            })

    return json.dumps({
        "query": query,
        "result_count": len(results),
        "ai_summary": response.summary or "",
        "results": results,
    }, ensure_ascii=False, indent=2)


def _no_sdk_response(query: str, tool_name: str) -> str:
    """Coze SDK 不可用时的返回"""
    return json.dumps({
        "error": f"联网搜索功能不可用（Coze SDK 未安装）",
        "query": query,
        "tool": tool_name,
        "suggestion": "请安装 coze-coding-dev-sdk 包，或使用其他搜索工具。"
    }, ensure_ascii=False, indent=2)


@tool
def search_market_data(query: str, count: int = 5) -> str:
    """
    联网搜索市场数据、行业报告、竞品信息。

    参数:
        query: 搜索关键词，如 "2024年中国咖啡市场规模" 或 "SaaS行业平均获客成本"
        count: 返回结果数量，默认 5

    返回: JSON 字符串，包含搜索结果摘要
    """
    if not _HAS_COZE_SDK:
        return _no_sdk_response(query, "search_market_data")

    try:
        response = _search_with_coze(query, count)
        return _format_results(response, query)
    except Exception as e:
        return json.dumps({
            "error": f"搜索失败: {str(e)}",
            "query": query,
            "suggestion": "请稍后重试，或尝试更精确的搜索关键词。"
        }, ensure_ascii=False)


@tool
def search_competitor_info(company_or_product: str, industry: str = "") -> str:
    """
    搜索竞争对手信息。

    参数:
        company_or_product: 竞品公司名或产品名
        industry: 所属行业（可选，帮助缩小范围）

    返回: JSON 字符串，包含竞品信息摘要
    """
    if not _HAS_COZE_SDK:
        return _no_sdk_response(f"{company_or_product} {industry}", "search_competitor_info")

    try:
        query = f"{company_or_product} {industry} 商业模式 融资 用户规模"
        response = _search_with_coze(query, 5)

        results = []
        if response.web_items:
            for item in response.web_items:
                results.append({
                    "title": item.title or "",
                    "url": item.url or "",
                    "snippet": (item.snippet or "")[:250],
                    "source": item.site_name or "",
                })

        return json.dumps({
            "target": company_or_product,
            "industry": industry,
            "result_count": len(results),
            "ai_summary": response.summary or "",
            "results": results,
            "note": "联网搜索结果仅供参考，建议交叉验证关键数据。"
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({
            "error": f"搜索失败: {str(e)}",
            "suggestion": "请稍后重试。"
        }, ensure_ascii=False)


@tool
def search_industry_benchmarks(industry: str, metric: str = "") -> str:
    """
    搜索行业基准数据（毛利率、获客成本、增长率等）。

    参数:
        industry: 行业名称，如 "SaaS" "餐饮" "电商"
        metric: 具体指标，如 "毛利率" "获客成本" "增长率"，留空则搜索综合基准

    返回: JSON 字符串，包含行业基准数据
    """
    if not _HAS_COZE_SDK:
        return _no_sdk_response(f"{industry} {metric}", "search_industry_benchmarks")

    try:
        metric_text = metric if metric else "行业平均 毛利率 获客成本 增长率"
        query = f"{industry} {metric_text} 2024 2025"

        response = _search_with_coze(query, 5)

        results = []
        if response.web_items:
            for item in response.web_items:
                results.append({
                    "title": item.title or "",
                    "url": item.url or "",
                    "snippet": (item.snippet or "")[:250],
                    "source": item.site_name or "",
                })

        return json.dumps({
            "industry": industry,
            "metric": metric or "综合",
            "result_count": len(results),
            "ai_summary": response.summary or "",
            "results": results,
            "note": "行业基准数据会随时间变化，建议定期更新。不同地区的基准可能有显著差异。"
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({
            "error": f"搜索失败: {str(e)}",
            "suggestion": "请稍后重试。"
        }, ensure_ascii=False)
