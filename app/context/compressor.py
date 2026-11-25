"""长堆栈错误窗口提取与 Tool Result 摘要压缩器。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.gateway_client.client import estimate_tokens

_ERROR_ANCHOR_RE = re.compile(
    r"(Caused by:|Exception|Error\b|FATAL|ERROR|Traceback|Timeout|OutOfMemory|Deadlock)",
    re.IGNORECASE,
)
_NOISY_FRAME_RE = re.compile(
    r"^\s*at\s+(org\.springframework|io\.netty|sun\.reflect|jdk\.internal|java\.lang\.reflect|org\.apache\.catalina|org\.apache\.tomcat)\."
)
_BIZ_FRAME_RE = re.compile(r"^\s*at\s+(com\.logops|com\.gateway|com\.mall|app\.)")


@dataclass
class CompressedResult:
    """压缩输出与节省指标。"""

    content: str
    original_chars: int
    compressed_chars: int
    original_tokens: int
    compressed_tokens: int
    truncated: bool

    @property
    def compression_ratio(self) -> float:
        if self.original_chars == 0:
            return 0.0
        return round(1.0 - (self.compressed_chars / self.original_chars), 4)


def extract_error_window(
    text: str,
    *,
    max_lines: int = 40,
    context_before: int = 4,
    context_after: int = 12,
) -> str:
    """从超长日志或 Java/Python 堆栈中提取核心错误窗口并折叠框架冗余帧。"""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text

    # 1. 优先识别所有异常锚点行及 Caused by 行
    anchor_indices: list[int] = [
        idx for idx, line in enumerate(lines) if _ERROR_ANCHOR_RE.search(line)
    ]

    if not anchor_indices:
        head = lines[: max_lines // 2]
        tail = lines[-(max_lines - len(head)) :]
        omitted = len(lines) - len(head) - len(tail)
        return "\n".join(head + [f"... [省略中间 {omitted} 行正常日志] ..."] + tail)

    selected_indices: set[int] = set()
    # 聚焦第一个异常与最后一个 Caused by 根因异常
    focus_anchors = [anchor_indices[0]]
    caused_by = [i for i in anchor_indices if "caused by" in lines[i].lower()]
    if caused_by:
        focus_anchors.append(caused_by[-1])
    elif len(anchor_indices) > 1:
        focus_anchors.append(anchor_indices[-1])

    for anchor in focus_anchors:
        start = max(0, anchor - context_before)
        end = min(len(lines), anchor + context_after + 1)
        for idx in range(start, end):
            selected_indices.add(idx)

    # 补充保留所有业务包堆栈帧
    for idx, line in enumerate(lines):
        if _BIZ_FRAME_RE.match(line):
            selected_indices.add(idx)

    # 折叠连续框架堆栈噪声帧
    output_lines: list[str] = []
    noisy_streak = 0
    last_idx = -1

    for idx in sorted(selected_indices):
        if last_idx != -1 and idx > last_idx + 1:
            output_lines.append(f"... [跳过 {idx - last_idx - 1} 行非核心上下文] ...")
        line = lines[idx]
        if _NOISY_FRAME_RE.match(line):
            noisy_streak += 1
            if noisy_streak <= 2:
                output_lines.append(line)
            elif noisy_streak == 3:
                output_lines.append("    ... [折叠第三方框架冗余堆栈帧] ...")
        else:
            noisy_streak = 0
            output_lines.append(line)
        last_idx = idx
        if len(output_lines) >= max_lines:
            output_lines.append(f"... [已达窗口上限 {max_lines} 行，截断剩余内容] ...")
            break

    return "\n".join(output_lines)


def compress_tool_result(
    text: str,
    *,
    max_chars: int = 1600,
    source_label: str = "tool_output",
) -> CompressedResult:
    """对 MCP 工具返回的日志或代码片段进行错误窗口提取 + 长度预算压缩。"""
    orig_chars = len(text)
    orig_tokens = estimate_tokens(text)

    if orig_chars <= max_chars:
        return CompressedResult(
            content=text,
            original_chars=orig_chars,
            compressed_chars=orig_chars,
            original_tokens=orig_tokens,
            compressed_tokens=orig_tokens,
            truncated=False,
        )

    windowed = extract_error_window(text, max_lines=32, context_before=3, context_after=8)
    if len(windowed) > max_chars:
        keep_head = int(max_chars * 0.65)
        keep_tail = max_chars - keep_head - 64
        windowed = (
            windowed[:keep_head]
            + f"\n... [{source_label} 已压缩截断，原始 {orig_chars} 字符] ...\n"
            + windowed[-max(0, keep_tail) :]
        )

    comp_chars = len(windowed)
    comp_tokens = estimate_tokens(windowed)
    return CompressedResult(
        content=windowed,
        original_chars=orig_chars,
        compressed_chars=comp_chars,
        original_tokens=orig_tokens,
        compressed_tokens=comp_tokens,
        truncated=True,
    )
