"""敏感数据脱敏器：对长堆栈和日志中的手机号、邮箱、Token、密码、密钥等进行掩码替换。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SanitizeResult:
    """脱敏结果与审计统计。"""

    sanitized_text: str
    redaction_counts: dict[str, int] = field(default_factory=dict)

    @property
    def total_redactions(self) -> int:
        return sum(self.redaction_counts.values())


# 按优先级排序的敏感信息规则（高特异性优先，避免误伤堆栈行号）
_REDACTION_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "jwt_token",
        re.compile(r"Bearer\s+eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", re.IGNORECASE),
        "Bearer [REDACTED_JWT]",
    ),
    (
        "raw_jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        "[REDACTED_JWT]",
    ),
    (
        "api_key",
        re.compile(r"\b(?:sk|ak|pk|rk)-[A-Za-z0-9_-]{12,}\b"),
        "[REDACTED_API_KEY]",
    ),
    (
        "jdbc_password",
        re.compile(r"(password|passwd|pwd|secret|token|api_key|access_key)\s*([=:])\s*([^\s,;\"'&]+)", re.IGNORECASE),
        r"\1\2[REDACTED_SECRET]",
    ),
    (
        "auth_header",
        re.compile(r"(Authorization\s*:\s*)(?!Bearer\s+\[REDACTED)([^\r\n]+)", re.IGNORECASE),
        r"\1[REDACTED_AUTH]",
    ),
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    (
        "cn_id_card",
        re.compile(r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b"),
        "[REDACTED_ID_CARD]",
    ),
    (
        "cn_phone",
        re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)"),
        r"\1****\2",
    ),
]


def sanitize_text(text: str) -> SanitizeResult:
    """对输入日志或堆栈文本执行敏感字段脱敏，返回脱敏文本与各类命中次数。"""
    if not text:
        return SanitizeResult(sanitized_text="")

    current = text
    counts: dict[str, int] = {}
    for label, pattern, replacement in _REDACTION_PATTERNS:
        current, hit = pattern.subn(replacement, current)
        if hit > 0:
            counts[label] = counts.get(label, 0) + hit

    return SanitizeResult(sanitized_text=current, redaction_counts=counts)
