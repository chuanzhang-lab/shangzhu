"""路由器包 — 意图路由 + 参数提取 + 模板格式化"""
from .intent import detect_intent, detect_intent_safe
from .param_extractor import extract_params
from .formatter import format_response

__all__ = ["detect_intent", "detect_intent_safe", "extract_params", "format_response"]
