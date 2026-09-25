"""冻结一次完整实验的代码、数据、指标和结果文件。"""

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def copy_artifact(source: Path, target_dir: Path) -> dict:
    target = target_dir / source.name
    shutil.copy2(source, target)
    return {
        "source": str(source.relative_to(ROOT)).replace("\\", "/"),
        "artifact": str(target.relative_to(ROOT)).replace("\\", "/"),
        "sha256": sha256(source),
        "size": source.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="冻结一次 RAG 完整实验")
    parser.add_argument("--name", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--judged", required=True)
    parser.add_argument("--judge-report", required=True)
    parser.add_argument("--layer-metrics", required=True)
    args = parser.parse_args()

    experiment_dir = ROOT / "eval/experiments" / args.name
    experiment_dir.mkdir(parents=True, exist_ok=True)
    dataset = Path(args.dataset)
    if not dataset.is_absolute():
        dataset = ROOT / dataset
    artifacts = {}
    for key, value in {
        "dataset": dataset,
        "raw_results": Path(args.raw),
        "judged_results": Path(args.judged),
        "judge_report": Path(args.judge_report),
        "layer_metrics": Path(args.layer_metrics),
    }.items():
        if not value.is_absolute():
            value = ROOT / value
        artifacts[key] = copy_artifact(value, experiment_dir)

    source_files = [
        ROOT / "app/rag_service.py",
        ROOT / "app/query_planner.py",
        ROOT / "app/answer_validator.py",
        ROOT / "app/evidence_selector.py",
        ROOT / "app/answer_verifier.py",
        ROOT / "app/prompts.py",
    ]
    manifest = {
        "experiment": args.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "artifacts": artifacts,
        "source_sha256": {
            str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path)
            for path in source_files
            if path.exists()
        },
        "configuration": {
            "embedding_model": config.EMBEDDING_MODEL,
            "embedding_batch_size": config.EMBEDDING_BATCH_SIZE,
            "embedding_max_concurrency": config.EMBEDDING_MAX_CONCURRENCY,
            "embedding_query_batch": config.EMBEDDING_QUERY_BATCH_ENABLED,
            "rerank_model": config.RERANK_MODEL,
            "llm_model": config.LLM_MODEL,
            "top_k": config.TOP_K,
            "retrieve_candidates": config.RETRIEVE_CANDIDATES,
            "rerank_candidates": config.RERANK_CANDIDATES,
            "parent_expansion": config.PARENT_EXPANSION_ENABLED,
            "neighbor_expansion": config.NEIGHBOR_EXPANSION_ENABLED,
            "neighbor_conditional": config.NEIGHBOR_CONDITIONAL_ENABLED,
            "query_planner": config.QUERY_PLANNER_ENABLED,
            "query_clarification": config.QUERY_CLARIFICATION_ENABLED,
            "evidence_coverage": config.EVIDENCE_COVERAGE_ENABLED,
            "query_rewrite": config.QUERY_REWRITE_ENABLED,
            "standalone_query_rewrite": config.QUERY_REWRITE_STANDALONE_ENABLED,
            "multi_query": config.MULTI_QUERY_ENABLED,
            "multi_query_max_queries": config.MULTI_QUERY_MAX_QUERIES,
            "multi_query_max_workers": config.MULTI_QUERY_MAX_WORKERS,
            "multi_query_rrf_k": config.MULTI_QUERY_RRF_K,
            "answer_verification": config.ANSWER_VERIFICATION_ENABLED,
            "trace_enabled": config.RAG_TRACE_ENABLED,
        },
    }
    manifest_path = experiment_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(str(manifest_path))


if __name__ == "__main__":
    main()
