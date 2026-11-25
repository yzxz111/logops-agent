"""Markdown 故障手册解析与分块器，保留 doc_id、服务名、错误码与精确行号溯源。"""

from __future__ import annotations

import re
from pathlib import Path

from app.rag.schemas import KnowledgeChunk

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")


def _parse_frontmatter(raw_text: str) -> tuple[dict[str, str], str, int]:
    """解析简单 YAML Frontmatter，返回元数据、正文以及正文起始行号（1-based）。"""
    match = _FRONTMATTER_RE.match(raw_text)
    if not match:
        return {}, raw_text, 1

    meta_block = match.group(1)
    meta: dict[str, str] = {}
    for line in meta_block.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip().strip('"').strip("'")

    consumed = raw_text[: match.end()]
    start_line = consumed.count("\n") + 1
    return meta, raw_text[match.end() :], start_line


def load_and_chunk_markdown_dir(knowledge_dir: Path) -> list[KnowledgeChunk]:
    """扫描知识库目录下的全部 Markdown 故障手册并按章节分块。"""
    if not knowledge_dir.exists():
        return []

    chunks: list[KnowledgeChunk] = []
    for md_path in sorted(knowledge_dir.glob("*.md")):
        raw = md_path.read_text(encoding="utf-8")
        meta, body, body_start_line = _parse_frontmatter(raw)

        doc_id = meta.get("doc_id") or md_path.stem
        title = meta.get("title") or md_path.stem
        service = meta.get("service") or "unknown"
        error_code = meta.get("error_code") or "UNKNOWN"
        severity = meta.get("severity") or "P1"
        kw_raw = meta.get("keywords", "")
        keywords = [k.strip() for k in kw_raw.split(",") if k.strip()]
        rel_source = md_path.name

        lines = body.splitlines()
        sections: list[tuple[str, int, int, list[str]]] = []
        cur_section = "概览"
        cur_start = body_start_line
        cur_lines: list[str] = []

        for offset, line in enumerate(lines):
            abs_line = body_start_line + offset
            heading_match = _HEADING_RE.match(line)
            if heading_match and heading_match.group(1) in {"#", "##"}:
                if cur_lines and any(l.strip() for l in cur_lines):
                    sections.append((cur_section, cur_start, abs_line - 1, cur_lines))
                cur_section = heading_match.group(2).strip()
                cur_start = abs_line
                cur_lines = [line]
            else:
                cur_lines.append(line)

        if cur_lines and any(l.strip() for l in cur_lines):
            end_line = body_start_line + len(lines) - 1
            sections.append((cur_section, cur_start, max(cur_start, end_line), cur_lines))

        for idx, (sec_name, l_start, l_end, sec_lines) in enumerate(sections, start=1):
            text_body = "\n".join(sec_lines).strip()
            if len(text_body) < 12:
                continue
            enriched_content = (
                f"[{doc_id}] {title} | 服务: {service} | 错误码: {error_code} | 章节: {sec_name}\n"
                f"{text_body}"
            )
            chunks.append(
                KnowledgeChunk(
                    chunk_id=f"{doc_id}#c{idx}",
                    doc_id=doc_id,
                    title=title,
                    service=service,
                    error_code=error_code,
                    severity=severity,
                    section=sec_name,
                    content=enriched_content,
                    source_path=f"data/knowledge/{rel_source}",
                    line_start=l_start,
                    line_end=l_end,
                    keywords=keywords,
                )
            )
    return chunks
