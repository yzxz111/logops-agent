"""基于官方 MCP SDK (FastMCP) 暴露只读排障工具的 MCP Server 入口。"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.mcp_tools.schemas import LogQueryInput, SourceSearchInput
from app.mcp_tools.tools import query_service_logs, search_source_code

mcp = FastMCP("logops-readonly-tools")


@mcp.tool(
    name="query_service_logs",
    description="只读查询微服务或网关的模拟日志切片，支持按服务名、报错关键词和 TraceID 检索，返回脱敏压缩后的异常上下文。",
)
def mcp_query_service_logs(
    service: str,
    keyword: str = "",
    trace_id: str = "",
    window_lines: int = 6,
    max_matches: int = 5,
) -> dict:
    """只读日志切片检索 MCP 工具。"""
    params = LogQueryInput(
        service=service,
        keyword=keyword,
        trace_id=trace_id,
        window_lines=window_lines,
        max_matches=max_matches,
    )
    return query_service_logs(params).model_dump()


@mcp.tool(
    name="search_source_code",
    description="只读检索模拟源码库中的类、方法、异常定义或配置项关键词，返回文件路径、行号范围与代码片段。",
)
def mcp_search_source_code(
    keyword: str,
    service: str = "",
    context_lines: int = 5,
    max_matches: int = 5,
) -> dict:
    """只读源码关键词定位 MCP 工具。"""
    params = SourceSearchInput(
        keyword=keyword,
        service=service,
        context_lines=context_lines,
        max_matches=max_matches,
    )
    return search_source_code(params).model_dump()


if __name__ == "__main__":
    mcp.run(transport="stdio")
