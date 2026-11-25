"""MCP 工具 Pydantic v2 参数校验与结构化返回模型。"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_SAFE_SERVICE_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_SAFE_TRACE_RE = re.compile(r"^[a-zA-Z0-9_.:-]{0,128}$")


class LogQueryInput(BaseModel):
    """日志切片检索工具入参（只读）。"""

    service: str = Field(..., description="服务名称，例如 gateway / order-service / auth-service")
    keyword: str = Field(default="", max_length=128, description="报错关键词或错误码，如 504 / Deadlock / Timeout")
    trace_id: str = Field(default="", max_length=128, description="可选 TraceID / Request-ID")
    window_lines: int = Field(default=6, ge=1, le=30, description="命中行前后扩展行数")
    max_matches: int = Field(default=5, ge=1, le=20, description="最多返回匹配片段数")

    @field_validator("service")
    @classmethod
    def validate_service_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not _SAFE_SERVICE_RE.match(cleaned):
            raise ValueError(f"非法服务名 '{v}'：仅允许字母、数字、下划线与短横线")
        if ".." in cleaned or "/" in cleaned or "\\" in cleaned:
            raise ValueError("禁止路径穿越字符")
        return cleaned

    @field_validator("trace_id")
    @classmethod
    def validate_trace_id(cls, v: str) -> str:
        cleaned = v.strip()
        if not _SAFE_TRACE_RE.match(cleaned):
            raise ValueError(f"非法 trace_id '{v}'")
        return cleaned


class LogSlice(BaseModel):
    """单条命中日志切片。"""

    file: str
    start_line: int
    end_line: int
    matched_line: int
    content: str


class LogQueryResult(BaseModel):
    """日志检索工具返回结构。"""

    service: str
    total_matches: int
    slices: list[LogSlice] = Field(default_factory=list)
    compressed_summary: str = ""
    note: str = ""


class SourceSearchInput(BaseModel):
    """源码关键词定位工具入参（只读）。"""

    keyword: str = Field(..., min_length=1, max_length=128, description="源码关键词、类名、方法名或配置项")
    service: str = Field(default="", max_length=64, description="可选限定服务目录")
    context_lines: int = Field(default=5, ge=1, le=20, description="代码上下文行数")
    max_matches: int = Field(default=5, ge=1, le=15, description="最多返回代码位置数")

    @field_validator("service")
    @classmethod
    def validate_optional_service(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            return ""
        if not _SAFE_SERVICE_RE.match(cleaned):
            raise ValueError(f"非法服务目录名 '{v}'")
        return cleaned

    @field_validator("keyword")
    @classmethod
    def validate_keyword(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("keyword 不能为空")
        if ".." in cleaned:
            raise ValueError("keyword 包含非法路径序列")
        return cleaned


class SourceMatch(BaseModel):
    """单处源码匹配片段。"""

    file: str
    start_line: int
    end_line: int
    matched_line: int
    snippet: str


class SourceSearchResult(BaseModel):
    """源码检索工具返回结构。"""

    keyword: str
    total_matches: int
    matches: list[SourceMatch] = Field(default_factory=list)
    compressed_summary: str = ""
    note: str = ""
