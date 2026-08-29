"""
报告生成工具 — PDF/Excel 输出

Coze SDK 可用时使用 DocumentGenerationClient，
不可用时本地生成文件。
"""

import json
import os
import time
import tempfile
from typing import Optional
from langchain.tools import tool

# output/ 目录文件数上限与 TTL，防止长期运行磁盘无限增长
_MAX_OUTPUT_FILES = 50
_OUTPUT_FILE_TTL_SECONDS = 3600 * 24  # 24 小时

# 尝试导入 Coze SDK
try:
    from coze_coding_dev_sdk import DocumentGenerationClient, DocumentFormat
    _HAS_COZE_SDK = True
except ImportError:
    _HAS_COZE_SDK = False

# 尝试导入 openpyxl（本地 Excel 生成）
try:
    import openpyxl
    _HAS_OPENPYXL = True
except ImportError:
    _HAS_OPENPYXL = False


def _cleanup_output_dir(output_dir: str) -> None:
    """清理 output/ 目录：删除过期文件 + 限制文件总数上限。"""
    if not os.path.isdir(output_dir):
        return
    now = time.time()
    files = []
    for f in os.listdir(output_dir):
        fp = os.path.join(output_dir, f)
        if os.path.isfile(fp):
            try:
                mtime = os.path.getmtime(fp)
                if now - mtime > _OUTPUT_FILE_TTL_SECONDS:
                    os.remove(fp)
                else:
                    files.append((mtime, fp))
            except OSError:
                pass
    # 按修改时间倒序排列，只保留最新 _MAX_OUTPUT_FILES 个
    if len(files) > _MAX_OUTPUT_FILES:
        files.sort(key=lambda x: x[0], reverse=True)
        for _, fp in files[_MAX_OUTPUT_FILES:]:
            try:
                os.remove(fp)
            except OSError:
                pass


def _generate_excel_url(data: list[dict], title: str, sheet_name: str = "Sheet1") -> str:
    """生成 Excel 文件并返回路径"""
    if _HAS_COZE_SDK:
        client = DocumentGenerationClient()
        return client.create_xlsx_from_list(data, title, sheet_name)

    # 本地生成
    if not _HAS_OPENPYXL:
        raise RuntimeError("openpyxl 未安装，无法生成 Excel")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name

    if data:
        # 写入表头
        headers = list(data[0].keys())
        for col, header in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=header)

        # 写入数据
        for row_idx, row_data in enumerate(data, 2):
            for col_idx, header in enumerate(headers, 1):
                ws.cell(row=row_idx, column=col_idx, value=row_data.get(header, ""))

    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "output")
    os.makedirs(output_dir, exist_ok=True)
    _cleanup_output_dir(output_dir)  # R2 修复：写文件前先清理过期/超限文件
    output_path = os.path.join(output_dir, f"{title}.xlsx")
    wb.save(output_path)
    return f"file://{os.path.abspath(output_path)}"


def _generate_pdf_url(markdown_content: str, title: str) -> str:
    """生成 PDF 文件，Coze 不可用时保存为 Markdown"""
    if _HAS_COZE_SDK:
        client = DocumentGenerationClient()
        return client.create_pdf_from_markdown(markdown_content, title)

    # 本地降级：保存为 Markdown 文件
    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "output")
    os.makedirs(output_dir, exist_ok=True)
    _cleanup_output_dir(output_dir)  # R2 修复：写文件前先清理过期/超限文件
    output_path = os.path.join(output_dir, f"{title}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    return f"file://{os.path.abspath(output_path)}"


def _generate_docx_url(markdown_content: str, title: str) -> str:
    """生成 DOCX 文件，Coze 不可用时保存为 Markdown"""
    if _HAS_COZE_SDK:
        client = DocumentGenerationClient()
        return client.create_docx_from_markdown(markdown_content, title)

    # 本地降级：保存为 Markdown 文件
    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "output")
    os.makedirs(output_dir, exist_ok=True)
    _cleanup_output_dir(output_dir)  # R2 修复：写文件前先清理过期/超限文件
    output_path = os.path.join(output_dir, f"{title}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    return f"file://{os.path.abspath(output_path)}"


@tool
def generate_financial_report(
    report_content_markdown: str,
    report_title: str = "financial_report",
) -> str:
    """
    生成财务分析报告（PDF 格式）。

    参数:
        report_content_markdown: Markdown 格式的报告内容
        report_title: 报告标题（仅英文字母/数字/下划线，用于文件名）

    返回: JSON 字符串，包含 PDF 下载 URL
    """
    try:
        safe_title = "".join(c for c in report_title if c.isalnum() or c == "_")[:50] or "financial_report"

        url = _generate_pdf_url(report_content_markdown, safe_title)

        return json.dumps({
            "success": True,
            "format": "PDF" if _HAS_COZE_SDK else "Markdown (本地)",
            "title": safe_title,
            "download_url": url,
            "note": "下载链接 24 小时内有效。" if _HAS_COZE_SDK else "Coze SDK 不可用，已保存为本地 Markdown 文件。"
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"报告生成失败: {str(e)}",
            "suggestion": "请检查 Markdown 内容是否合法，或稍后重试。"
        }, ensure_ascii=False)


@tool
def generate_financial_excel(
    sheets_json: str,
    report_title: str = "financial_model",
) -> str:
    """
    生成财务模型 Excel 文件。

    参数:
        sheets_json: JSON 字符串，每个元素为 {"sheet_name": "...", "data": [...]}
                     其中 data 为字典列表或二维列表
        report_title: 报告标题（仅英文字母/数字/下划线，用于文件名）

    返回: JSON 字符串，包含 Excel 下载 URL
    """
    try:
        sheets = json.loads(sheets_json)
        if not sheets:
            return json.dumps({"error": "sheets_json 不能为空"}, ensure_ascii=False)

        safe_title = "".join(c for c in report_title if c.isalnum() or c == "_")[:50] or "financial_model"

        first_sheet = sheets[0]
        data = first_sheet.get("data", [])
        sheet_name = first_sheet.get("sheet_name", "Sheet1")

        url = _generate_excel_url(data, safe_title, sheet_name)

        return json.dumps({
            "success": True,
            "format": "XLSX",
            "title": safe_title,
            "sheet_count": len(sheets),
            "download_url": url,
            "note": "下载链接 24 小时内有效。当前仅输出第一个 Sheet，多 Sheet 支持开发中。"
        }, ensure_ascii=False, indent=2)

    except json.JSONDecodeError:
        return json.dumps({"error": "sheets_json 格式错误"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Excel 生成失败: {str(e)}"
        }, ensure_ascii=False)


@tool
def generate_business_canvas_report(
    canvas_json: str,
    report_title: str = "business_canvas",
) -> str:
    """
    生成商业模式画布报告（PDF 格式）。

    参数:
        canvas_json: JSON 字符串，包含画布 9 大模块
        report_title: 报告标题（仅英文）

    返回: JSON 字符串，包含 PDF 下载 URL
    """
    try:
        canvas = json.loads(canvas_json)

        fields = {
            "价值主张": canvas.get("value_proposition", "未填写"),
            "客户细分": canvas.get("customer_segments", "未填写"),
            "渠道通路": canvas.get("channels", "未填写"),
            "客户关系": canvas.get("customer_relationships", "未填写"),
            "收入来源": canvas.get("revenue_streams", "未填写"),
            "核心资源": canvas.get("key_resources", "未填写"),
            "关键业务": canvas.get("key_activities", "未填写"),
            "重要伙伴": canvas.get("key_partners", "未填写"),
            "成本结构": canvas.get("cost_structure", "未填写"),
        }

        md = f"""# 商业模式画布

## 项目：{report_title}

| 模块 | 内容 |
|------|------|
"""
        for k, v in fields.items():
            md += f"| **{k}** | {v} |\n"

        md += """
---

## 逻辑一致性检查

请检查以下问题：
1. 价值主张是否真正解决了客户细分群体的痛点？
2. 收入来源是否与客户细分的支付能力和意愿匹配？
3. 渠道通路是否与目标客户的使用习惯一致？
4. 成本结构是否与收入来源匹配？是否存在未覆盖的隐性成本？
5. 关键资源和关键活动是否足以支撑价值主张的交付？
"""

        safe_title = "".join(c for c in report_title if c.isalnum() or c == "_")[:50] or "business_canvas"

        url = _generate_pdf_url(md, safe_title)

        return json.dumps({
            "success": True,
            "format": "PDF" if _HAS_COZE_SDK else "Markdown (本地)",
            "title": safe_title,
            "download_url": url,
            "fields_count": sum(1 for v in fields.values() if v != "未填写"),
            "total_fields": 9,
            "note": "下载链接 24 小时内有效。" if _HAS_COZE_SDK else "Coze SDK 不可用，已保存为本地 Markdown 文件。"
        }, ensure_ascii=False, indent=2)

    except json.JSONDecodeError:
        return json.dumps({"error": "canvas_json 格式错误"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"画布报告生成失败: {str(e)}"
        }, ensure_ascii=False)


def build_report_markdown(scan: dict, title: str = "商业建模分析报告") -> str:
    """把 quick_scan 结果整理成 Markdown 报告正文。"""
    lines = [f"# {title}", ""]
    lines.append(f"- 项目类型：{scan.get('project_type', '未知')}")
    lines.append(f"- 阶段：{scan.get('stage', '未知')}")
    lines.append("")

    core = scan.get("core_metrics", {})
    lines.append("## 核心指标")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    for k, v in core.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    status = scan.get("status", {})
    if status:
        lines.append("## 状态评估")
        for k, v in status.items():
            lines.append(f"- {k}: {v}")
        lines.append("")

    if scan.get("narrative"):
        lines.append("## 风险聚焦")
        lines.append(f"> {scan['narrative']}")
        lines.append("")

    sens = scan.get("sensitivity", {}).get("scenarios", [])
    if sens:
        lines.append("## 敏感性分析")
        lines.append("| 场景 | 月利润 |")
        lines.append("|------|--------|")
        for s in sens:
            name = s.get("name", "")
            profit = s.get("monthly_profit")
            lines.append(f"| {name} | {profit} |")
        lines.append("")

    pits = scan.get("pitfalls", {}).get("pitfalls", [])
    if pits:
        lines.append("## 风险清单")
        for p in pits:
            lines.append(f"- {p.get('level', '')} {p.get('message', '')}")
        lines.append("")

    return "\n".join(lines)


def build_excel_sheets(scan: dict) -> list:
    """把 quick_scan 结果整理成 Excel sheet 结构。"""
    core_rows = []
    for k, v in scan.get("core_metrics", {}).items():
        core_rows.append({"指标": k, "数值": v})

    status_rows = []
    for k, v in scan.get("status", {}).items():
        status_rows.append({"维度": k, "评估": v})

    pit_rows = []
    for p in scan.get("pitfalls", {}).get("pitfalls", []):
        pit_rows.append({
            "级别": p.get("level", ""),
            "风险": p.get("message", ""),
        })

    return [
        {"sheet_name": "核心指标", "data": core_rows},
        {"sheet_name": "状态评估", "data": status_rows},
        {"sheet_name": "风险清单", "data": pit_rows},
    ]
