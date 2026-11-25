"""上下文处理模块：长堆栈敏感信息脱敏、错误窗口提取与工具结果压缩。"""

from app.context.compressor import (
    CompressedResult,
    compress_tool_result,
    extract_error_window,
)
from app.context.sanitizer import SanitizeResult, sanitize_text

__all__ = [
    "SanitizeResult",
    "sanitize_text",
    "CompressedResult",
    "extract_error_window",
    "compress_tool_result",
]
