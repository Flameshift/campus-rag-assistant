"""旁路 RAGAS 评测：读取冻结结果，不参与在线问答链路。"""

import argparse
import json
import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from importlib.metadata import version as package_version
from pathlib import Path

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
ENV = {
    **dotenv_values(ROOT / ".env"),
    **os.environ,
}


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def select_items(
    items: list[dict],
    limit: int,
    ids: set[str],
    include_unanswerable: bool,
    stratified: bool,
) -> list[dict]:
    selected = [
        item
        for item in items
        if (include_unanswerable or item.get("answerable"))
        and (not ids or item.get("id") in ids)
    ]
    if not limit or len(selected) <= limit:
        return selected
    if not stratified:
        return selected[:limit]

    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in selected:
        grouped[item.get("type") or "unknown"].append(item)
    result = []
    positions = {key: 0 for key in grouped}
    while len(result) < limit:
        added = False
        for type_name in sorted(grouped):
            position = positions[type_name]
            values = grouped[type_name]
            if position >= len(values):
                continue
            result.append(values[position])
            positions[type_name] += 1
            added = True
            if len(result) >= limit:
                break
        if not added:
            break
    return result


def sqlite_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("RAGAS 参考上下文当前仅支持 sqlite 数据库")
    value = database_url[len(prefix) :]
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_reference_contexts(items: list[dict]) -> dict[int, str]:
    chunk_ids = {
        int(chunk_id)
        for item in items
        for chunk_id in (item.get("source_chunk_ids") or [])
        if chunk_id is not None
    }
    if not chunk_ids:
        return {}
    database_path = sqlite_path(
        str(ENV.get("DATABASE_URL") or "sqlite:///./data/app.db")
    )
    connection = sqlite3.connect(database_path)
    try:
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = connection.execute(
            f"SELECT id, content FROM chunk WHERE id IN ({placeholders})",
            tuple(sorted(chunk_ids)),
        ).fetchall()
    finally:
        connection.close()
    return {int(row[0]): str(row[1]) for row in rows}


def clean_answer(answer: str) -> str:
    return re.split(r"\n---\n\*\*信息来源\*\*", answer or "", maxsplit=1)[0].strip()


def build_samples(items: list[dict], reference_contexts: dict[int, str]):
    from ragas import SingleTurnSample

    samples = []
    skipped = []
    for item in items:
        contexts = [
            context
            for chunk_id in item.get("source_chunk_ids") or []
            if (context := reference_contexts.get(int(chunk_id)))
        ]
        if not contexts:
            skipped.append(item.get("id"))
            continue
        samples.append(
            SingleTurnSample(
                user_input=item["question"],
                response=clean_answer(item.get("answer", "")),
                retrieved_contexts=[
                    str(source.get("content") or "")
                    for source in item.get("sources") or []
                    if source.get("content")
                ],
                reference=item.get("reference_answer", ""),
                reference_contexts=contexts,
            )
        )
    return samples, skipped


def build_evaluator(model: str):
    from langchain_openai import OpenAIEmbeddings as LangchainEmbeddings
    from openai import OpenAI
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import llm_factory

    api_key = ENV.get("RAGAS_LLM_API_KEY") or ENV["LLM_API_KEY"]
    base_url = ENV.get("RAGAS_LLM_BASE_URL") or ENV["LLM_BASE_URL"]
    llm_client = OpenAI(api_key=api_key, base_url=base_url)
    llm = llm_factory(
        model,
        provider="openai",
        client=llm_client,
    )
    embeddings = LangchainEmbeddingsWrapper(
        LangchainEmbeddings(
            api_key=ENV["EMBEDDING_API_KEY"],
            base_url=ENV["EMBEDDING_BASE_URL"],
            model=ENV["EMBEDDING_MODEL"],
            check_embedding_ctx_length=False,
        )
    )
    return llm, embeddings


def run(args) -> None:
    installed_ragas = package_version("ragas")
    if installed_ragas != "0.4.3":
        raise RuntimeError(
            "当前脚本依赖 RAGAS 0.4.3 的兼容接口，"
            f"检测到 {installed_ragas}。请使用 requirements-ragas.txt。"
        )
    from ragas import EvaluationDataset, RunConfig, evaluate
    from ragas.metrics._answer_correctness import answer_correctness
    from ragas.metrics._answer_relevance import answer_relevancy
    from ragas.metrics._context_precision import context_precision
    from ragas.metrics._context_recall import context_recall
    from ragas.metrics._faithfulness import faithfulness
    from ragas.metrics._noise_sensitivity import NoiseSensitivity

    judged_path = Path(args.judged)
    if not judged_path.is_absolute():
        judged_path = ROOT / judged_path
    items = load_jsonl(judged_path)
    selected = select_items(
        items,
        limit=args.limit,
        ids=set(filter(None, (args.ids or "").split(","))),
        include_unanswerable=args.include_unanswerable,
        stratified=args.stratified,
    )
    references = load_reference_contexts(selected)
    samples, skipped = build_samples(selected, references)
    if not samples:
        raise RuntimeError("没有可评测样本，请检查 source_chunk_ids 和数据库内容")

    llm, embeddings = build_evaluator(args.model)
    metrics = [
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall,
        answer_correctness,
        NoiseSensitivity(mode=args.noise_mode),
    ]
    dataset = EvaluationDataset(
        samples=samples,
        name=judged_path.stem,
    )
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        run_config=RunConfig(
            timeout=args.timeout,
            max_retries=args.max_retries,
            max_workers=args.workers,
            seed=42,
        ),
        raise_exceptions=False,
        show_progress=True,
    )

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    frame = result.to_pandas()
    csv_path = output_dir / f"ragas_{stamp}.csv"
    json_path = output_dir / f"ragas_{stamp}.json"
    frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
    metric_values = {
        column: float(frame[column].dropna().mean())
        for column in frame.select_dtypes(include="number").columns
        if frame[column].dropna().size
    }
    summary = {
        "source": str(judged_path.relative_to(ROOT)).replace("\\", "/"),
        "created_at": stamp,
        "model": args.model,
        "embedding_model": ENV["EMBEDDING_MODEL"],
        "sample_count": len(samples),
        "skipped": skipped,
        "metrics": metric_values,
        "csv": str(csv_path.relative_to(ROOT)).replace("\\", "/"),
    }
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="RAGAS 旁路评测")
    parser.add_argument("--judged", required=True)
    parser.add_argument("--output-dir", default="eval/reports/ragas")
    parser.add_argument(
        "--model",
        default=ENV.get("RAGAS_LLM_MODEL") or "qwen-flash",
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--ids", default="")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--noise-mode", choices=["relevant", "irrelevant"], default="irrelevant")
    parser.add_argument("--include-unanswerable", action="store_true")
    parser.add_argument("--no-stratified", action="store_true")
    args = parser.parse_args()
    args.stratified = not args.no_stratified
    run(args)


if __name__ == "__main__":
    main()
