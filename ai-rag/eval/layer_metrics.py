"""从 judged JSONL 计算检索、重排、上下文和生成的分层指标。"""

import argparse
import json
import re
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _fact_coverage(item: dict, source_text: str) -> float:
    facts = item.get("key_facts") or []
    if not facts:
        return 1.0
    return sum(1 for fact in facts if str(fact) in source_text) / len(facts)


def _citation_metrics(answer: str, source_count: int) -> tuple[float, float]:
    clean = answer.split("**信息来源**", 1)[0]
    sentences = [
        value.strip()
        for value in re.split(r"(?<=[。！？!?])|\n+", clean)
        if len(value.strip()) >= 6
    ]
    citations = [int(value) for value in re.findall(r"\[\s*证据\s*(\d+)\s*\]", clean)]
    coverage = min(1.0, len(citations) / len(sentences)) if sentences else 0.0
    valid = (
        sum(1 for value in citations if 1 <= value <= source_count) / len(citations)
        if citations
        else 0.0
    )
    return coverage, valid


def _ranked_source_ids(item: dict) -> list[int]:
    ids: list[int] = []
    for source in item.get("sources") or []:
        metadata = source.get("metadata", {})
        values = metadata.get("source_chunk_ids") or [metadata.get("chunk_id")]
        for value in values:
            if value is None:
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed not in ids:
                ids.append(parsed)
    return ids


def _retrieval_metrics(
    ranked_ids: list[int],
    ground_truth_ids: set[int],
) -> dict:
    if not ground_truth_ids:
        return {}
    result: dict[str, float] = {}
    reciprocal_rank = 0.0
    for rank, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in ground_truth_ids:
            reciprocal_rank = 1.0 / rank
            break
    for k in (1, 3, 5):
        top_k = ranked_ids[:k]
        hits = len(ground_truth_ids & set(top_k))
        result[f"recall_at_{k}"] = hits / len(ground_truth_ids)
        result[f"precision_at_{k}"] = hits / k
        result[f"hit_at_{k}"] = 1.0 if hits else 0.0
    result["mrr"] = reciprocal_rank
    return result


def _trace_metrics(item: dict) -> dict:
    trace_path_value = item.get("trace_path")
    if not trace_path_value:
        return {}
    trace_path = Path(trace_path_value)
    if not trace_path.exists():
        return {}
    try:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    values = trace.get("values") or {}
    stages = trace.get("stages") or {}

    def stage_tokens(name: str) -> float:
        documents = (stages.get(name) or {}).get("documents") or []
        return float(
            sum(
                float(document.get("estimated_tokens", 0) or 0)
                for document in documents
            )
        )

    candidate_tokens = stage_tokens("retrieval_candidates")
    reranked_tokens = stage_tokens("reranked")
    final_tokens = float(
        values.get("final_context_estimated_tokens", 0) or 0
    )
    compression_ratio = (
        final_tokens / candidate_tokens
        if candidate_tokens
        else None
    )
    return {
        "candidate_tokens": candidate_tokens,
        "reranked_tokens": reranked_tokens,
        "final_context_tokens": final_tokens,
        "context_compression_ratio": compression_ratio,
    }


def summarize(items: list[dict]) -> dict:
    rows = []
    for item in items:
        sources = item.get("sources") or []
        source_text = "\n".join(str(source.get("content") or "") for source in sources)
        ranked_source_ids = _ranked_source_ids(item)
        source_chunk_ids = set(ranked_source_ids)
        ground_truth_ids = {
            int(value)
            for value in item.get("source_chunk_ids") or []
            if value is not None
        }
        rerank_scores = [
            float(source.get("metadata", {}).get("rerank_score"))
            for source in sources
            if source.get("metadata", {}).get("rerank_score") is not None
        ]
        answer = str(item.get("answer") or "")
        citation_coverage, citation_validity = _citation_metrics(
            answer,
            len(sources),
        )
        confidence = item.get("confidence") or {}
        signals = confidence.get("signals") or {}
        timings = item.get("timings") or {}
        retrieval_metrics = _retrieval_metrics(
            ranked_source_ids,
            ground_truth_ids,
        )
        trace_metrics = _trace_metrics(item)
        rows.append(
            {
                "id": item.get("id"),
                "type": item.get("type"),
                "judge_score": item.get("judge_score"),
                "source_count": len(sources),
                "context_fact_coverage": _fact_coverage(item, source_text),
                "ground_truth_recall": (
                    len(ground_truth_ids & source_chunk_ids) / len(ground_truth_ids)
                    if ground_truth_ids
                    else None
                ),
                "rerank_top_score": max(rerank_scores) if rerank_scores else 0.0,
                "parent_expanded": any(
                    source.get("metadata", {}).get("expanded_parent")
                    for source in sources
                ),
                "citation_coverage": citation_coverage,
                "citation_validity": citation_validity,
                "retrieval_confidence": float(
                    confidence.get("retrieval_confidence", 0) or 0
                ),
                "generation_confidence": float(
                    confidence.get("generation_confidence", 0) or 0
                ),
                "claim_support_rate": float(
                    signals.get("claim_support_rate", 0) or 0
                ),
                "answer_repaired": bool(
                    float(timings.get("answer_repaired_count", 0) or 0)
                ),
                "latency_seconds": float(item.get("latency_seconds", 0) or 0),
                **retrieval_metrics,
                **trace_metrics,
            }
        )

    def aggregate(group: list[dict]) -> dict:
        scores = [row["judge_score"] for row in group]
        ground_truth = [
            row["ground_truth_recall"]
            for row in group
            if row["ground_truth_recall"] is not None
        ]
        latencies = [row["latency_seconds"] for row in group]
        compression = [
            row["context_compression_ratio"]
            for row in group
            if row.get("context_compression_ratio") is not None
        ]
        return {
            "count": len(group),
            "judge_avg_score": statistics.mean(scores) if scores else 0.0,
            "judge_correct_rate": (
                sum(1 for score in scores if score == 2) / len(scores)
                if scores
                else 0.0
            ),
            "avg_source_count": statistics.mean(
                row["source_count"] for row in group
            )
            if group
            else 0.0,
            "avg_context_fact_coverage": statistics.mean(
                row["context_fact_coverage"] for row in group
            )
            if group
            else 0.0,
            "avg_ground_truth_recall": statistics.mean(ground_truth)
            if ground_truth
            else None,
            "avg_rerank_top_score": statistics.mean(
                row["rerank_top_score"] for row in group
            )
            if group
            else 0.0,
            "parent_expansion_rate": (
                sum(1 for row in group if row["parent_expanded"]) / len(group)
                if group
                else 0.0
            ),
            "avg_citation_coverage": statistics.mean(
                row["citation_coverage"] for row in group
            )
            if group
            else 0.0,
            "avg_citation_validity": statistics.mean(
                row["citation_validity"] for row in group
            )
            if group
            else 0.0,
            "avg_retrieval_confidence": statistics.mean(
                row["retrieval_confidence"] for row in group
            )
            if group
            else 0.0,
            "avg_generation_confidence": statistics.mean(
                row["generation_confidence"] for row in group
            )
            if group
            else 0.0,
            "avg_claim_support_rate": statistics.mean(
                row["claim_support_rate"] for row in group
            )
            if group
            else 0.0,
            "answer_repair_rate": (
                sum(1 for row in group if row["answer_repaired"]) / len(group)
                if group
                else 0.0
            ),
            "latency_p50_seconds": _percentile(latencies, 0.5),
            "latency_p95_seconds": _percentile(latencies, 0.95),
            "recall_at_3": statistics.mean(
                row["recall_at_3"] for row in group if "recall_at_3" in row
            ) if any("recall_at_3" in row for row in group) else None,
            "precision_at_3": statistics.mean(
                row["precision_at_3"] for row in group if "precision_at_3" in row
            ) if any("precision_at_3" in row for row in group) else None,
            "hit_at_3": statistics.mean(
                row["hit_at_3"] for row in group if "hit_at_3" in row
            ) if any("hit_at_3" in row for row in group) else None,
            "precision_at_5": statistics.mean(
                row["precision_at_5"] for row in group if "precision_at_5" in row
            ) if any("precision_at_5" in row for row in group) else None,
            "mrr": statistics.mean(
                row["mrr"] for row in group if "mrr" in row
            ) if any("mrr" in row for row in group) else None,
            "avg_candidate_tokens": statistics.mean(
                row["candidate_tokens"] for row in group if "candidate_tokens" in row
            ) if any("candidate_tokens" in row for row in group) else None,
            "avg_final_context_tokens": statistics.mean(
                row["final_context_tokens"] for row in group if "final_context_tokens" in row
            ) if any("final_context_tokens" in row for row in group) else None,
            "avg_context_compression_ratio": statistics.mean(compression) if compression else None,
        }

    grouped = defaultdict(list)
    for row in rows:
        grouped[row["type"]].append(row)
    return {
        "overall": aggregate(rows),
        "by_type": {
            type_name: aggregate(group)
            for type_name, group in sorted(grouped.items())
        },
    }


def write_report(path: Path, source_path: Path, summary: dict) -> None:
    overall = summary["overall"]

    def percentage(value) -> str:
        return "-" if value is None else f"{value:.1%}"

    def number(value, digits: int = 2) -> str:
        return "-" if value is None else f"{value:.{digits}f}"

    lines = [
        "# RAG 分层指标报告",
        "",
        f"- 来源结果：`{source_path.name}`",
        f"- 题目数量：{overall['count']}",
        "",
        "## 总体指标",
        "",
        "| 层级 | 指标 | 数值 |",
        "| --- | --- | ---: |",
        f"| 检索 | 平均来源数（每次回答进入上下文的证据片段平均数量） | {overall['avg_source_count']:.2f} |",
        f"| 检索 | Recall@3（前 3 条来源覆盖真值分块的比例） | {percentage(overall.get('recall_at_3'))} |",
        f"| 检索 | Precision@3（前 3 条来源中的真值分块占比） | {percentage(overall.get('precision_at_3'))} |",
        f"| 检索 | Hit@3（前 3 条来源至少命中一个真值分块的题目比例） | {percentage(overall.get('hit_at_3'))} |",
        f"| 检索 | Precision@5（前 5 条来源中的真值分块占比） | {percentage(overall.get('precision_at_5'))} |",
        f"| 检索 | MRR（首个真值分块平均倒数排名） | {number(overall.get('mrr'), 4)} |",
        f"| 检索 | 上下文关键事实覆盖率（标准关键事实在检索上下文中出现的比例） | {overall['avg_context_fact_coverage']:.1%} |",
        f"| 检索 | Rerank Top-1 平均分（重排序后最高分证据的平均相关性分数） | {overall['avg_rerank_top_score']:.4f} |",
        f"| 检索 | 父级扩展命中率（至少一条证据通过父级扩展补入上下文的比例） | {overall['parent_expansion_rate']:.1%} |",
        f"| 生成 | 回答引用覆盖率（回答句子中带引用编号的比例） | {overall['avg_citation_coverage']:.1%} |",
        f"| 生成 | 引用编号有效率（回答中的引用编号能在来源列表中找到的比例） | {overall['avg_citation_validity']:.1%} |",
        f"| 生成 | Claim 支持率（回答中的事实性句子能被上下文证据支持的比例） | {overall['avg_claim_support_rate']:.1%} |",
        f"| 生成 | 回答补全触发率（回答完整性复核后触发二次补全的比例） | {overall['answer_repair_rate']:.1%} |",
        f"| 结果 | Judge 平均分（每道题语义评分的平均值，满分 2 分） | {overall['judge_avg_score']:.3f} |",
        f"| 结果 | 完全正确率（Judge 评分为 2 分的题目占比） | {overall['judge_correct_rate']:.1%} |",
        f"| 性能 | P50 延迟（50% 请求快于该耗时的请求耗时） | {overall['latency_p50_seconds']:.2f}s |",
        f"| 性能 | P95 延迟（95% 请求快于该耗时的请求耗时） | {overall['latency_p95_seconds']:.2f}s |",
        f"| 上下文 | 平均候选 Token（粗筛后进入 Rerank 的证据规模） | {number(overall.get('avg_candidate_tokens'), 1)} |",
        f"| 上下文 | 平均最终上下文 Token（最终送入生成的证据规模） | {number(overall.get('avg_final_context_tokens'), 1)} |",
        f"| 上下文 | 上下文压缩率（最终上下文 Token / 候选 Token） | {percentage(overall.get('avg_context_compression_ratio'))} |",
        "",
        "## 分题型指标",
        "",
        "| 类型 | 数量 | 正确率（Judge 2 分占比） | 上下文覆盖（关键事实命中比例） | 引用覆盖（带引用句子占比） | 补全率（二次回答触发比例） | P95（95% 请求耗时上限） |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for type_name, metrics in summary["by_type"].items():
        lines.append(
            f"| {type_name} | {metrics['count']} | "
            f"{metrics['judge_correct_rate']:.1%} | "
            f"{metrics['avg_context_fact_coverage']:.1%} | "
            f"{metrics['avg_citation_coverage']:.1%} | "
            f"{metrics['answer_repair_rate']:.1%} | "
            f"{metrics['latency_p95_seconds']:.2f}s |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="计算 RAG 分层指标")
    parser.add_argument("result", help="judged JSONL 文件")
    parser.add_argument("--output-dir", default="eval/reports")
    args = parser.parse_args()

    result_path = Path(args.result)
    summary = summarize(_load_jsonl(result_path))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"layer_metrics_{stamp}.json"
    md_path = output_dir / f"layer_metrics_{stamp}.md"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report(md_path, result_path, summary)
    print(json.dumps({
        "overall": summary["overall"],
        "json_report": str(json_path),
        "md_report": str(md_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
