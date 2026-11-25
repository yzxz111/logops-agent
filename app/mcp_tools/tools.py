"""只读 MCP 工具核心实现：日志切片检索 & 源码关键词定位（集成脱敏与压缩）。"""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.context.compressor import compress_tool_result
from app.context.sanitizer import sanitize_text
from app.mcp_tools.schemas import (
    LogQueryInput,
    LogQueryResult,
    LogSlice,
    SourceMatch,
    SourceSearchInput,
    SourceSearchResult,
)

_ALLOWED_SOURCE_SUFFIXES = {".java", ".py", ".yml", ".yaml", ".xml", ".conf", ".properties", ".sql"}


def _resolve_safe_child(base_dir: Path, relative_name: str) -> Path:
    """防路径穿越安全解析：确保目标路径严格位于 base_dir 下。"""
    resolved_base = base_dir.resolve()
    target = (resolved_base / relative_name).resolve()
    if target != resolved_base and resolved_base not in target.parents:
        raise ValueError(f"安全校验拦截：越权路径访问 '{relative_name}'")
    return target


def query_service_logs(
    params: LogQueryInput,
    *,
    logs_dir: Path | None = None,
) -> LogQueryResult:
    """只读检索指定服务的模拟日志文件，返回脱敏并压缩后的错误窗口切片。"""
    base_dir = logs_dir or get_settings().mock_logs_dir
    if not base_dir.exists():
        return LogQueryResult(
            service=params.service,
            total_matches=0,
            note=f"日志目录不存在: {base_dir}",
        )

    candidate_files: list[Path] = []
    exact_file = _resolve_safe_child(base_dir, f"{params.service}.log")
    if exact_file.is_file():
        candidate_files.append(exact_file)
    else:
        for file_path in sorted(base_dir.glob("*.log")):
            if params.service.lower() in file_path.stem.lower():
                candidate_files.append(file_path)

    if not candidate_files:
        return LogQueryResult(
            service=params.service,
            total_matches=0,
            note=f"未找到服务 '{params.service}' 对应的日志文件",
        )

    kw_lower = params.keyword.lower().strip()
    trace_lower = params.trace_id.lower().strip()
    slices: list[LogSlice] = []
    seen_ranges: set[tuple[str, int, int]] = set()

    for log_file in candidate_files:
        lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        for idx, line in enumerate(lines):
            line_lower = line.lower()
            hit_trace = bool(trace_lower and trace_lower in line_lower)
            hit_kw = bool(kw_lower and kw_lower in line_lower)
            hit_default_err = (not kw_lower and not trace_lower) and (
                "error" in line_lower or "exception" in line_lower or "warn" in line_lower
            )

            if trace_lower and kw_lower:
                matched = hit_trace or hit_kw
            elif trace_lower:
                matched = hit_trace
            elif kw_lower:
                matched = hit_kw
            else:
                matched = hit_default_err

            if not matched:
                continue

            start = max(0, idx - params.window_lines)
            end = min(len(lines), idx + params.window_lines + 1)
            key = (log_file.name, start, end)
            if key in seen_ranges:
                continue
            seen_ranges.add(key)

            raw_chunk = "\n".join(
                f"{ln + 1}: {lines[ln]}" for ln in range(start, end)
            )
            sanitized = sanitize_text(raw_chunk).sanitized_text
            slices.append(
                LogSlice(
                    file=log_file.name,
                    start_line=start + 1,
                    end_line=end,
                    matched_line=idx + 1,
                    content=sanitized,
                )
            )
            if len(slices) >= params.max_matches:
                break
        if len(slices) >= params.max_matches:
            break

    combined = "\n---\n".join(
        f"[{s.file}#L{s.start_line}-L{s.end_line}]\n{s.content}" for s in slices
    )
    compressed = compress_tool_result(combined, max_chars=900, source_label="log_slice")
    return LogQueryResult(
        service=params.service,
        total_matches=len(slices),
        slices=slices,
        compressed_summary=compressed.content,
        note="" if slices else "未检索到匹配的日志记录",
    )


def search_source_code(
    params: SourceSearchInput,
    *,
    source_dir: Path | None = None,
) -> SourceSearchResult:
    """只读检索模拟源码仓中的关键词、异常类或配置项，返回定位代码片段。"""
    base_dir = source_dir or get_settings().mock_source_dir
    if not base_dir.exists():
        return SourceSearchResult(
            keyword=params.keyword,
            total_matches=0,
            note=f"源码目录不存在: {base_dir}",
        )

    search_root = base_dir
    if params.service:
        scoped = _resolve_safe_child(base_dir, params.service)
        if scoped.is_dir():
            search_root = scoped

    kw_lower = params.keyword.lower()
    matches: list[SourceMatch] = []

    for path in sorted(search_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _ALLOWED_SOURCE_SUFFIXES:
            continue
        rel_path = path.relative_to(base_dir).as_posix()
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for idx, line in enumerate(lines):
            if kw_lower not in line.lower():
                continue
            start = max(0, idx - params.context_lines)
            end = min(len(lines), idx + params.context_lines + 1)
            raw_snippet = "\n".join(
                f"{ln + 1}: {lines[ln]}" for ln in range(start, end)
            )
            sanitized = sanitize_text(raw_snippet).sanitized_text
            matches.append(
                SourceMatch(
                    file=rel_path,
                    start_line=start + 1,
                    end_line=end,
                    matched_line=idx + 1,
                    snippet=sanitized,
                )
            )
            if len(matches) >= params.max_matches:
                break
        if len(matches) >= params.max_matches:
            break

    combined = "\n---\n".join(
        f"[{m.file}#L{m.start_line}-L{m.end_line}]\n{m.snippet}" for m in matches
    )
    compressed = compress_tool_result(combined, max_chars=900, source_label="source_code")
    return SourceSearchResult(
        keyword=params.keyword,
        total_matches=len(matches),
        matches=matches,
        compressed_summary=compressed.content,
        note="" if matches else "未找到匹配源码片段",
    )
