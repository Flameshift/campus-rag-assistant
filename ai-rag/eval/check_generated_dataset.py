"""对自动生成测试集做确定性检查和可选 LLM 抽样复核。"""

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from langchain_core.documents import Document
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.rag_service import rag_service  # noqa: E402
from eval.generate_dataset import (  # noqa: E402
    DEFAULT_EXISTING,
    _call_json,
    _load_jsonl,
    _normalize_question,
    _verifier_prompt,
)


REQUIRED_FIELDS = {
    "id",
    "question",
    "type",
    "answerable",
    "reference_answer",
    "key_facts",
    "history",
    "source",
    "source_section",
}

REFUSAL_PATTERN = re.compile(r"未规定|未提供|未覆盖|没有相关|无法|不能编造|不能忽略")
TIME_PATTERN = re.compile(r"天|日|月|年|工作日|期限|学期|学年|内")
SUBJECT_PATTERN = re.compile(
    r"学院|办公室|辅导员|教务处|委员会|学生处|部门|中心|班长|领导|教师"
)
STRICT_KEY_FACT_TYPES = {"fact", "table", "procedure", "multi_hop", "comparison"}


def _docs_by_chunk() -> dict[int, Document]:
    result = rag_service.vectorstore.get(include=["documents", "metadatas"])
    documents = {}
    for content, metadata in zip(
        result.get("documents", []),
        result.get("metadatas", []),
    ):
        metadata = dict(metadata or {})
        chunk_id = metadata.get("chunk_id")
        if chunk_id is not None:
            documents[int(chunk_id)] = Document(page_content=content, metadata=metadata)
    return documents


def _static_check(items: list[dict], existing: list[dict], docs: dict[int, Document]) -> dict:
    errors = []
    warnings = []
    ids = set()
    questions = set()
    existing_questions = {
        _normalize_question(item.get("question", ""))
        for item in existing
    }
    parent_ids = {
        str(document.metadata.get("parent_id"))
        for document in docs.values()
        if document.metadata.get("parent_id")
    }

    for index, item in enumerate(items, 1):
        item_id = str(item.get("id") or f"row-{index}")
        missing = sorted(REQUIRED_FIELDS - set(item))
        if missing:
            errors.append({"id": item_id, "error": f"缺少字段: {', '.join(missing)}"})
            continue
        if item_id in ids:
            errors.append({"id": item_id, "error": "ID 重复"})
        ids.add(item_id)

        question = str(item.get("question") or "").strip()
        reference = str(item.get("reference_answer") or "").strip()
        normalized = _normalize_question(question)
        if normalized in questions:
            errors.append({"id": item_id, "error": "候选池内问题重复"})
        if normalized in existing_questions:
            errors.append({"id": item_id, "error": "与正式测试集重复"})
        questions.add(normalized)

        if len(question) < 4 or len(reference) < 2:
            errors.append({"id": item_id, "error": "问题或标准答案过短"})

        key_facts = item.get("key_facts") or []
        if item.get("answerable", True):
            if not key_facts:
                errors.append({"id": item_id, "error": "可答案题缺少 key_facts"})
            for fact in key_facts:
                if str(fact) not in reference:
                    target = (
                        errors
                        if item.get("type") in STRICT_KEY_FACT_TYPES
                        else warnings
                    )
                    target.append(
                        {
                            "id": item_id,
                            (
                                "error"
                                if item.get("type") in STRICT_KEY_FACT_TYPES
                                else "warning"
                            ): f"关键事实需要语义复核: {fact}",
                        }
                    )
            chunk_ids = [int(value) for value in item.get("source_chunk_ids") or []]
            if not chunk_ids:
                errors.append({"id": item_id, "error": "可答案题缺少来源分块"})
            for chunk_id in chunk_ids:
                if chunk_id not in docs:
                    errors.append({"id": item_id, "error": f"来源分块不存在: {chunk_id}"})
            for parent_id in item.get("source_parent_ids") or []:
                if str(parent_id) not in parent_ids:
                    warnings.append({"id": item_id, "warning": f"父级不存在: {parent_id}"})
        else:
            if key_facts:
                errors.append({"id": item_id, "error": "无答案题不应包含关键事实"})
            if not REFUSAL_PATTERN.search(reference):
                errors.append({"id": item_id, "error": "无答案题未明确拒答"})

        if item.get("type") == "ambiguous_reference":
            history = item.get("history") or []
            if len(history) < 2:
                errors.append({"id": item_id, "error": "多轮题 history 不完整"})
            if "多久" in question and not TIME_PATTERN.search(reference):
                errors.append({"id": item_id, "error": "多轮题询问时限但答案无时限"})
            if "找谁" in question and not SUBJECT_PATTERN.search(reference):
                errors.append({"id": item_id, "error": "多轮题询问主体但答案无主体"})

        if item.get("type") == "verbose" and question.count("？") > 1:
            errors.append({"id": item_id, "error": "verbose 题包含多个问题"})
        if item.get("type") == "mixed_intent" and not re.search(
            r"另外|同时|分别|还有|以及",
            question,
        ):
            warnings.append({"id": item_id, "warning": "mixed_intent 未使用明确分隔词"})

    by_type = Counter(str(item.get("type")) for item in items)
    return {
        "total": len(items),
        "by_type": dict(sorted(by_type.items())),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def _sample_items(items: list[dict], limit: int, seed: int) -> list[dict]:
    if limit <= 0 or limit >= len(items):
        return list(items)
    rng = random.Random(seed)
    grouped = defaultdict(list)
    for item in items:
        grouped[item["type"]].append(item)
    selected = []
    while len(selected) < limit:
        progressed = False
        for group in grouped.values():
            if group and len(selected) < limit:
                selected.append(group.pop(rng.randrange(len(group))))
                progressed = True
        if not progressed:
            break
    return selected


def _llm_audit(items: list[dict], docs: dict[int, Document], args) -> dict:
    if args.llm_audit <= 0:
        return {"enabled": False, "sample": 0, "accepted": 0, "rejected": 0, "results": []}

    sample = _sample_items(items, args.llm_audit, args.seed)
    client = OpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL,
        timeout=args.timeout,
        max_retries=1,
    )

    def audit(item: dict) -> dict:
        evidence = [
            docs[int(chunk_id)]
            for chunk_id in item.get("source_chunk_ids") or []
            if int(chunk_id) in docs
        ]
        verdict = _call_json(
            client,
            args.model,
            _verifier_prompt(item, evidence),
        )
        return {
            "id": item["id"],
            "type": item["type"],
            "verdict": verdict.get("verdict"),
            "reason": verdict.get("reason"),
        }

    results = []
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(audit, item): item for item in sample}
        for future in as_completed(futures):
            item = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append({"id": item["id"], "error": str(exc)})
    results.sort(key=lambda item: item["id"])
    accepted = sum(1 for item in results if item.get("verdict") == "accept")
    rejected = sum(1 for item in results if item.get("verdict") == "reject")
    return {
        "enabled": True,
        "sample": len(sample),
        "accepted": accepted,
        "rejected": rejected,
        "errors": errors,
        "results": results,
    }


def _write_report(path: Path, report: dict) -> None:
    lines = [
        "# 自动生成测试集自检报告",
        "",
        f"- 生成时间：{report['created_at']}",
        f"- 候选总数：{report['static']['total']}",
        f"- 确定性错误：{report['static']['error_count']}",
        f"- 确定性警告：{report['static']['warning_count']}",
        f"- 严格通过集：{report['clean_count']}",
        f"- 待复核集：{report['review_count']}",
        f"- LLM 抽样复核：{report['llm_audit']['sample']}",
        f"- LLM 接受：{report['llm_audit']['accepted']}",
        f"- LLM 拒绝：{report['llm_audit']['rejected']}",
        "",
        "## 题型分布",
        "",
        "| 类型 | 数量 |",
        "| --- | ---: |",
    ]
    for type_name, count in report["static"]["by_type"].items():
        lines.append(f"| {type_name} | {count} |")

    lines += ["", "## 确定性错误", ""]
    if report["static"]["errors"]:
        for item in report["static"]["errors"]:
            lines.append(f"- `{item['id']}`：{item['error']}")
    else:
        lines.append("无")

    lines += ["", "## 确定性警告", ""]
    if report["static"]["warnings"]:
        for item in report["static"]["warnings"]:
            lines.append(f"- `{item['id']}`：{item['warning']}")
    else:
        lines.append("无")

    lines += ["", "## LLM 抽样复核", ""]
    if report["llm_audit"]["results"]:
        for item in report["llm_audit"]["results"]:
            lines.append(
                f"- `{item['id']}` [{item['type']}] {item['verdict']}："
                f"{item['reason']}"
            )
    else:
        lines.append("未启用")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_filtered_items(
    report_dir: Path,
    stamp: str,
    items: list[dict],
    review_ids: set[str],
) -> tuple[Path, Path, int, int]:
    clean = [item for item in items if str(item.get("id")) not in review_ids]
    review = [item for item in items if str(item.get("id")) in review_ids]
    clean_path = report_dir / f"clean_candidates_{stamp}.jsonl"
    review_path = report_dir / f"review_candidates_{stamp}.jsonl"
    for path, values in ((clean_path, clean), (review_path, review)):
        with path.open("w", encoding="utf-8") as stream:
            for item in values:
                stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    return clean_path, review_path, len(clean), len(review)


def run(args) -> None:
    input_path = Path(args.input)
    items = _load_jsonl(input_path)
    existing = []
    for path in DEFAULT_EXISTING:
        existing.extend(_load_jsonl(path))
    docs = _docs_by_chunk()

    report = {
        "created_at": datetime.now().isoformat(),
        "input": str(input_path),
        "static": _static_check(items, existing, docs),
        "llm_audit": _llm_audit(items, docs, args),
    }
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"self_check_{stamp}.json"
    md_path = report_dir / f"self_check_{stamp}.md"
    review_ids = {
        str(item["id"])
        for item in report["static"]["errors"] + report["static"]["warnings"]
    }
    clean_path, review_path, clean_count, review_count = _write_filtered_items(
        report_dir,
        stamp,
        items,
        review_ids,
    )
    report["clean_count"] = clean_count
    report["review_count"] = review_count
    report["artifacts"] = {
        "clean_candidates": str(clean_path),
        "review_candidates": str(review_path),
    }
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_report(md_path, report)
    print(json.dumps({
        "candidate_count": report["static"]["total"],
        "static_errors": report["static"]["error_count"],
        "static_warnings": report["static"]["warning_count"],
        "llm_sample": report["llm_audit"]["sample"],
        "llm_accepted": report["llm_audit"]["accepted"],
        "llm_rejected": report["llm_audit"]["rejected"],
        "clean_count": clean_count,
        "review_count": review_count,
        "clean_candidates": str(clean_path),
        "review_candidates": str(review_path),
        "json_report": str(json_path),
        "md_report": str(md_path),
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="检查自动生成测试集")
    parser.add_argument("input", help="candidate_pool JSONL")
    parser.add_argument("--llm-audit", type=int, default=20, help="LLM 分层抽样数量")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260918)
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--report-dir", default="eval/generated/reports")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
