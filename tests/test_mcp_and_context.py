"""只读 MCP 工具、Pydantic 校验与长堆栈脱敏压缩单元测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.context.compressor import compress_tool_result, extract_error_window
from app.context.sanitizer import sanitize_text
from app.mcp_tools.schemas import LogQueryInput, SourceSearchInput
from app.mcp_tools.tools import query_service_logs, search_source_code


def test_sanitize_sensitive_fields() -> None:
    raw = (
        "ERROR user_phone=13812345678 email=alice@corp.com "
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123456789 "
        "password=MySecret99 api_key=sk-1234567890abcdef1234"
    )
    res = sanitize_text(raw)
    assert "13812345678" not in res.sanitized_text
    assert "138****5678" in res.sanitized_text
    assert "alice@corp.com" not in res.sanitized_text
    assert "MySecret99" not in res.sanitized_text
    assert "sk-1234567890abcdef1234" not in res.sanitized_text
    assert res.total_redactions >= 4


def test_extract_error_window_and_compress_long_stack() -> None:
    noisy_frames = "\n".join(
        f"\tat org.springframework.web.FilterChain.doFilter(FilterChain.java:{i})"
        for i in range(1, 55)
    )
    long_stack = (
        "2026-11-25 INFO starting request\n"
        "java.lang.RuntimeException: outer failure\n"
        f"{noisy_frames}\n"
        "Caused by: java.sql.SQLTransientConnectionException: HikariPool-1 timeout\n"
        "\tat com.logops.order.OrderService.createOrder(OrderService.java:45)\n"
    )
    windowed = extract_error_window(long_stack, max_lines=25)
    assert "HikariPool-1 timeout" in windowed
    assert "com.logops.order.OrderService.createOrder" in windowed
    assert "折叠第三方框架冗余堆栈帧" in windowed

    compressed = compress_tool_result(long_stack, max_chars=500)
    assert compressed.truncated is True
    assert compressed.compression_ratio > 0.5


def test_mcp_pydantic_validation_blocks_traversal() -> None:
    with pytest.raises(ValidationError):
        LogQueryInput(service="../../etc/passwd", keyword="root")
    with pytest.raises(ValidationError):
        SourceSearchInput(keyword="../secrets")


def test_mcp_readonly_tools_query_logs_and_source() -> None:
    log_res = query_service_logs(LogQueryInput(service="order-service", keyword="HikariPool-1"))
    assert log_res.total_matches >= 1
    assert "138****5678" in log_res.compressed_summary  # 验证查询日志时也执行了脱敏

    src_res = search_source_code(SourceSearchInput(keyword="createOrder", service="order-service"))
    assert src_res.total_matches >= 1
    assert "OrderService.java" in src_res.matches[0].file
