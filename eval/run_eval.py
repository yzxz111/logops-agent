"""30 条故障评测脚本：输出 RAG 召回对比数据、工具调用准确率、根因命中率与脱敏/压缩统计。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.agent.graph import LogOpsAgentService
from app.config import PROJECT_ROOT, Settings
from app.rag.pipeline import HybridRagPipeline
from app.rag.schemas import SearchMode


def _evaluate_rag_mode(
    rag: HybridRagPipeline,
    cases: list[dict[str, Any]],
    mode: SearchMode,
) -> dict[str, float]:
    r1 = r3 = r5 = mrr_sum = 0.0
    total = len(cases)
    for case in cases:
        expected = set(case["expected_doc_ids"])
        res = rag.search(case["query"], top_k=5, mode=mode)
        doc_ids: list[str] = []
        for c in res.citations:
            if c.doc_id not in doc_ids:
                doc_ids.append(c.doc_id)

        if any(d in expected for d in doc_ids[:1]):
            r1 += 1
        if any(d in expected for d in doc_ids[:3]):
            r3 += 1
        if any(d in expected for d in doc_ids[:5]):
            r5 += 1

        rr = 0.0
        for rank, did in enumerate(doc_ids, start=1):
            if did in expected:
                rr = 1.0 / rank
                break
        mrr_sum += rr

    return {
        "Recall@1": round(r1 / total, 4),
        "Recall@3": round(r3 / total, 4),
        "Recall@5": round(r5 / total, 4),
        "MRR": round(mrr_sum / total, 4),
    }


async def run_evaluation(
    dataset_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    ds_path = dataset_path or (PROJECT_ROOT / "eval" / "dataset.json")
    out_dir = output_dir or (PROJECT_ROOT / "eval")
    cases = json.loads(ds_path.read_text(encoding="utf-8"))

    settings = Settings(llm_provider="mock", qdrant_mode="memory")
    rag = HybridRagPipeline(settings)
    chunk_count = rag.index_knowledge()
    agent = LogOpsAgentService(settings=settings, rag_pipeline=rag)

    # 1. 对比不同 RAG 模式下的召回指标（Baseline vs 优化后）
    rag_comparison = {
        mode: _evaluate_rag_mode(rag, cases, mode)
        for mode in ("bm25_only", "vector_only", "hybrid_rrf", "agentic")
    }

    # 2. 全链路 LangGraph + MCP 工具 + 人工确认评测
    tool_hits = 0
    root_cause_hits = 0
    high_risk_expected = 0
    high_risk_caught = 0
    retry_triggered = 0
    total_raw_chars = 0
    total_comp_chars = 0
    case_details: list[dict[str, Any]] = []

    for case in cases:
        res = await agent.run_diagnosis(case["query"], request_id=f"eval-{case['id']}")
        if res["status"] == "waiting_human_confirm":
            high_risk_caught += 1
            res = await agent.resume_diagnosis(
                res["thread_id"],
                approved=False,
                comment="eval 自动安全降级",
            )

        if case.get("has_high_risk_action"):
            high_risk_expected += 1

        called_tools = {t["tool"] for t in res.get("tool_calls", [])}
        expected_tools = set(case.get("expected_tools", []))
        tool_matched = expected_tools.issubset(called_tools) if expected_tools else True
        if tool_matched:
            tool_hits += 1

        combined_out = f"{res.get('root_cause', '')}\n{res.get('final_report', '')}".lower()
        rc_keywords = case.get("expected_root_cause_keywords", [])
        rc_matched = any(kw.lower() in combined_out for kw in rc_keywords)
        if rc_matched:
            root_cause_hits += 1

        if res.get("retry_count", 0) > 0:
            retry_triggered += 1

        for tc in res.get("tool_calls", []):
            total_raw_chars += tc.get("raw_chars", 0)
            total_comp_chars += tc.get("compressed_chars", 0)

        case_details.append({
            "id": case["id"],
            "status": res["status"],
            "top_doc": res["rag_citations"][0]["doc_id"] if res["rag_citations"] else None,
            "tools": list(called_tools),
            "tool_matched": tool_matched,
            "root_cause_matched": rc_matched,
            "steps": res["step_count"],
            "tokens": res["token_used"],
            "retry_count": res["retry_count"],
        })

    total = len(cases)
    compression_ratio = (
        round(1.0 - (total_comp_chars / total_raw_chars), 4)
        if total_raw_chars > 0
        else 0.0
    )

    summary = {
        "total_cases": total,
        "indexed_chunks": chunk_count,
        "rag_comparison": rag_comparison,
        "agent_metrics": {
            "tool_accuracy": round(tool_hits / total, 4),
            "root_cause_hit_rate": round(root_cause_hits / total, 4),
            "high_risk_interception_rate": round(
                high_risk_caught / max(1, high_risk_expected), 4
            ),
            "secondary_retrieval_triggered_cases": retry_triggered,
            "tool_context_compression_ratio": compression_ratio,
        },
        "case_details": case_details,
    }

    (out_dir / "eval_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    md_lines = [
        "# LogOps-Agent 30 条故障评测报告",
        "",
        f"- **知识库分块总数**: {chunk_count}",
        f"- **评测集样本数**: {total}",
        "",
        "## 1. RAG 检索优化前后对比",
        "",
        "| 检索模式 | Recall@1 | Recall@3 | Recall@5 | MRR |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for mode, m in rag_comparison.items():
        md_lines.append(
            f"| `{mode}` | {m['Recall@1']:.2%} | {m['Recall@3']:.2%} | {m['Recall@5']:.2%} | {m['MRR']:.4f} |"
        )

    am = summary["agent_metrics"]
    md_lines.extend([
        "",
        "## 2. Agent 全链路能力指标",
        "",
        f"- **只读 MCP 工具调用准确率**: {am['tool_accuracy']:.2%}",
        f"- **根因定位命中率**: {am['root_cause_hit_rate']:.2%}",
        f"- **高危指令人工确认拦截率**: {am['high_risk_interception_rate']:.2%} ({high_risk_caught}/{high_risk_expected})",
        f"- **触发二次检索样本数**: {am['secondary_retrieval_triggered_cases']}",
        f"- **工具上下文压缩率**: {am['tool_context_compression_ratio']:.2%}",
    ])
    (out_dir / "eval_report.md").write_text("\n".join(md_lines), encoding="utf-8")
    return summary


if __name__ == "__main__":
    report = asyncio.run(run_evaluation())
    print(json.dumps({k: v for k, v in report.items() if k != "case_details"}, ensure_ascii=False, indent=2))
