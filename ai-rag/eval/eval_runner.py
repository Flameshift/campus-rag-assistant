"""学生手册 RAG 评估脚本。

读取 student_handbook_questions.jsonl，逐题调用问答接口，
记录回答、来源、延迟以及关键事实命中情况，输出到 eval/results/。

用法：
    python eval/eval_runner.py
    python eval/eval_runner.py --api http://127.0.0.1:8080/api/chat --limit 10

说明：
- key_facts 命中率只是关键词覆盖率，不等于语义正确率；
- 最终评分仍建议结合人工复核或 LLM-as-Judge。
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import hmac
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import config

EVAL_DIR = PROJECT_ROOT / "eval"
DEFAULT_INPUT = EVAL_DIR / "student_handbook_questions.jsonl"
DEFAULT_OUTPUT_DIR = EVAL_DIR / "results"
DEFAULT_API = "http://127.0.0.1:8080/api/chat"

REFUSAL_KEYWORDS = [
    "未规定",
    "未提及",
    "未明确",
    "未覆盖",
    "未说明",
    "没有相关",
    "手册没有",
    "不包含",
    "无法确认",
    "无法确定",
    "无法回答",
]


def load_questions(path: Path) -> list[dict]:
    """读取 JSONL 评估集，跳过空行。"""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def ask(
    api_url: str,
    question: str,
    history: list[dict] | None = None,
    timeout: int = 180,
) -> tuple[dict, float]:
    """调用问答接口，返回 (响应数据, 耗时秒数)。"""
    payload = json.dumps({"question": question, "history": history or []}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if config.INTERNAL_AUTH_REQUIRED:
        timestamp = str(int(time.time()))
        signed_path = urlsplit(api_url).path
        signature_payload = f"{timestamp}\nPOST\n{signed_path}".encode("utf-8")
        signature = hmac.new(
            config.INTERNAL_AUTH_SECRET.encode("utf-8"),
            signature_payload,
            hashlib.sha256,
        ).hexdigest()
        headers.update(
            {
                "X-Internal-Timestamp": timestamp,
                "X-Internal-Signature": signature,
            }
        )
    request = urllib.request.Request(
        api_url,
        data=payload,
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data, time.perf_counter() - started


def score_answer(item: dict, answer: str) -> dict:
    """按题型做基础自动评分。"""
    if not item["answerable"]:
        refused = any(keyword in answer for keyword in REFUSAL_KEYWORDS)
        return {"refused": refused}

    facts = item.get("key_facts", [])
    hits = [fact for fact in facts if fact in answer]
    return {
        "fact_hits": hits,
        "fact_hit_rate": round(len(hits) / len(facts), 3) if facts else None,
    }


def run(args) -> None:
    questions = load_questions(Path(args.input))
    if args.ids:
        selected_ids = {item.strip() for item in args.ids.split(",") if item.strip()}
        questions = [item for item in questions if item["id"] in selected_ids]
    if args.limit:
        questions = questions[: args.limit]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"run_{stamp}.jsonl"

    def run_one(index: int, item: dict) -> tuple[int, dict]:
        try:
            data, latency = ask(
                args.api,
                item["question"],
                item.get("history", []),
                args.timeout,
            )
            answer = data.get("answer", "")
            sources = data.get("sources", [])
            mode = data.get("mode", "")
            timings = data.get("timings", {})
            confidence = data.get("confidence", {})
            request_id = data.get("request_id", "")
            error = ""
        except Exception as exc:  # 网络或接口错误也要记录，不能中断整轮
            answer = ""
            sources = []
            mode = ""
            timings = {}
            confidence = {}
            request_id = ""
            latency = 0.0
            error = str(exc)

        result = {
            **item,
            "answer": answer,
            "source_count": len(sources),
            # 保留实际召回证据，后续 Judge 和检索问题定位不再只能看 source_count。
            "sources": sources,
            "mode": mode,
            "timings": timings,
            "confidence": confidence,
            "latency_seconds": round(latency, 3),
            "error": error,
        }
        if request_id:
            trace_path = Path(config.RAG_TRACE_DIR) / f"{request_id}.json"
            if trace_path.exists():
                result["trace_path"] = str(trace_path)
        result.update(score_answer(item, answer))
        print(f"[{index}/{len(questions)}] {item['id']} 延迟={latency:.2f}s 错误={error or '-'}")
        return index, result

    indexed_results: dict[int, dict] = {}
    workers = max(1, min(args.workers, len(questions))) if questions else 1

    if workers == 1:
        for index, item in enumerate(questions, start=1):
            result_index, result = run_one(index, item)
            indexed_results[result_index] = result
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(run_one, index, item): index
                for index, item in enumerate(questions, start=1)
            }
            for future in as_completed(futures):
                result_index, result = future.result()
                indexed_results[result_index] = result

    results = [indexed_results[index] for index in sorted(indexed_results)]

    with output_path.open("w", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")

    answerable = [r for r in results if r["answerable"]]
    unanswerable = [r for r in results if not r["answerable"]]
    avg_fact_rate = (
        sum(r.get("fact_hit_rate") or 0 for r in answerable) / len(answerable) if answerable else 0
    )
    refusal_rate = (
        sum(1 for r in unanswerable if r.get("refused")) / len(unanswerable) if unanswerable else 0
    )
    avg_latency = sum(r["latency_seconds"] for r in results) / len(results) if results else 0
    errors = sum(1 for r in results if r["error"])

    print("\n===== 评估汇总 =====")
    print(f"题目总数: {len(results)}")
    print(f"有答案题目: {len(answerable)}，平均关键事实覆盖率: {avg_fact_rate:.1%}")
    print(f"无答案题目: {len(unanswerable)}，拒答率: {refusal_rate:.1%}")
    print(f"平均延迟: {avg_latency:.2f}s")
    print(f"接口错误: {errors}")
    print(f"结果文件: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="学生手册 RAG 评估脚本")
    parser.add_argument("--api", default=DEFAULT_API, help="问答接口地址")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="评估集 JSONL 路径")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="结果输出目录")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题，0 表示全部")
    parser.add_argument("--ids", default="", help="只运行指定 ID，多个 ID 用逗号分隔")
    parser.add_argument("--timeout", type=int, default=180, help="单题请求超时秒数")
    parser.add_argument("--workers", type=int, default=1, help="并发题目数，默认 1")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
