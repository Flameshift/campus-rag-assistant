"""检索诊断脚本：分析指定题目的召回与排序情况。

用法：
    python eval/diagnose_questions.py sh-009 sh-028 sh-060

输出：
    eval/results/diagnose_<ids>.md
"""

import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR.parent))

from app import config  # noqa: E402
from app.rag_service import rag_service  # noqa: E402
from app.reranker import reranker  # noqa: E402

DATASET = EVAL_DIR / "student_handbook_questions.jsonl"
DEFAULT_RESULTS = EVAL_DIR / "results" / "run_20260912_213128_judged.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def format_docs(name: str, docs: list, key_facts: list[str], lines: list[str]) -> None:
    lines.append(f"### {name}（{len(docs)} 条）")
    lines.append("")
    lines.append("| 排名 | chunk_id | page | 命中关键事实 | 内容摘要 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for rank, doc in enumerate(docs, start=1):
        hits = [fact for fact in key_facts if fact in doc.page_content]
        excerpt = doc.page_content.replace("\n", " ")[:60]
        lines.append(
            f"| {rank} | {doc.metadata.get('chunk_id')} | {doc.metadata.get('page')} | "
            f"{'、'.join(hits) if hits else '-'} | {excerpt} |"
        )
    lines.append("")


def main() -> None:
    ids = sys.argv[1:] or ["sh-009", "sh-028", "sh-060"]
    dataset = {item["id"]: item for item in load_jsonl(DATASET)}
    results = {item["id"]: item for item in load_jsonl(DEFAULT_RESULTS)}

    lines = ["# 检索诊断报告", ""]
    for qid in ids:
        item = dataset.get(qid)
        result = results.get(qid, {})
        if not item:
            continue

        question = item["question"]
        key_facts = item.get("key_facts", [])
        lines += [
            f"## {qid}（{item['type']}）",
            "",
            f"**问题**：{question}",
            "",
            f"**标准答案**：{item['reference_answer']}",
            "",
            f"**关键事实**：{'、'.join(key_facts) or '无'}",
            "",
            f"**评判分数**：{result.get('judge_score')}",
            "",
            f"**评判理由**：{result.get('judge_reason', '')}",
            "",
            f"**模型回答摘要**：{(result.get('answer') or '').replace(chr(10), ' ')[:220]}",
            "",
        ]

        vector_docs = rag_service.vector_retriever.invoke(question)
        bm25_docs = rag_service.bm25_retriever.invoke(question) if rag_service.bm25_retriever else []
        ensemble_docs = rag_service.retriever.invoke(question)
        rerank_candidates = ensemble_docs[: config.RERANK_CANDIDATES]
        final_docs = reranker.rerank(question, rerank_candidates)[: config.TOP_K]

        lines += [
            f"**候选数量**：向量 {len(vector_docs)} / BM25 {len(bm25_docs)} / "
            f"融合 {len(ensemble_docs)} / Rerank 候选 {len(rerank_candidates)} / "
            f"最终进入 Prompt {len(final_docs)}",
            "",
        ]
        format_docs("向量检索", vector_docs, key_facts, lines)
        format_docs("BM25 关键词检索", bm25_docs, key_facts, lines)
        format_docs("融合检索（Ensemble）", ensemble_docs, key_facts, lines)
        format_docs("Rerank 后进入 Prompt", final_docs, key_facts, lines)

        all_text = "\n".join(doc.page_content for doc in ensemble_docs)
        missing = [fact for fact in key_facts if fact not in all_text]
        lines += [
            "**召回诊断**：",
            "",
            f"- 关键事实未出现在任何候选中的：{'、'.join(missing) if missing else '无'}",
            f"- 若为空说明问题在“排序或生成”，不是召回缺失。",
            "",
        ]

    output = EVAL_DIR / "results" / f"diagnose_{'_'.join(ids)}.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
