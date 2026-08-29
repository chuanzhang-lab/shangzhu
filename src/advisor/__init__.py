"""顾问面板子包 — 格式化 LLM 输出为顾问面板 JSON。

职责：把 llm_advisor.advise 的输出格式化为顾问面板所需的结构化 JSON，
包含判断、风险、建议动作、依据标注。

约束（CALCULATION_PHILOSOPHY.md 14 条纪律）：
- 不做公式求值（#1 公式唯一出处）
- 不直接写状态（#2 合并安全）
- 引用数字必须带来源标签（#11 来源必标）
- 不引用 [候选] 值作为建议依据（#6 保守兜底）
- 数字防火墙：过滤 LLM 输出中任何未在参数面板出现的数字（防 #1 被攻破）
"""

from advisor.advisor_formatter import format_advice, validate_no_computed_numbers

__all__ = ["format_advice", "validate_no_computed_numbers"]
