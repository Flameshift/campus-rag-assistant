"""Evaluate cohort-aware applicability fallback behavior."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import hmac
import json
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402


def ask(api_url: str, item: dict, timeout: int) -> tuple[dict, float]:
    payload = json.dumps(
        {
            "question": item["question"],
            "history": item.get("history") or [],
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if config.INTERNAL_AUTH_REQUIRED:
        timestamp = str(int(time.time()))
        path = urlsplit(api_url).path
        signed = f"{timestamp}\nPOST\n{path}".encode("utf-8")
        signature = hmac.new(
            config.INTERNAL_AUTH_SECRET.encode("utf-8"),
            signed,
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
        return json.loads(response.read().decode("utf-8")), time.perf_counter() - started


def evaluate_item(item: dict, response: dict) -> dict:
    answer = str(response.get("answer") or "")
    expected_mode = item.get("expected_mode") or ""
    mode_match = _mode_matches(expected_mode, answer)
    missing = [value for value in item.get("must_include") or [] if value not in answer]
    forbidden = [
        value
        for value in item.get("must_not_include") or []
        if value in answer
    ]
    return {
        **item,
        "answer": answer,
        "confidence": response.get("confidence") or {},
        "timings": response.get("timings") or {},
        "mode_match": mode_match,
        "missing_required_text": missing,
        "forbidden_text": forbidden,
        "passed": mode_match and not missing and not forbidden,
    }


def _mode_matches(expected_mode: str, answer: str) -> bool:
    if expected_mode == "exact":
        return "往届参考" not in answer and "你未说明所在年级" not in answer
    if expected_mode == "fallback":
        return "往届参考" in answer and "未收录" in answer
    if expected_mode == "latest_current":
        return "你未说明所在年级" in answer and "适用对象" in answer
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="年级适用范围评测")
    parser.add_argument("--input", required=True)
    parser.add_argument("--api", default="http://127.0.0.1:8080/api/chat")
    parser.add_argument("--output-dir", default="eval/results")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids", default="")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    items = [
        json.loads(line)
        for line in input_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.ids:
        selected_ids = {value.strip() for value in args.ids.split(",") if value.strip()}
        items = [item for item in items if item.get("id") in selected_ids]
    if args.limit:
        items = items[: args.limit]

    def run_one(item: dict) -> dict:
        response, latency = ask(args.api, item, args.timeout)
        result = evaluate_item(item, response)
        result["latency_seconds"] = latency
        return result

    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(run_one, item) for item in items]
        for future in as_completed(futures):
            results.append(future.result())

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"cohort_applicability_{stamp}.jsonl"
    with output_path.open("w", encoding="utf-8") as stream:
        for item in results:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")

    passed = sum(1 for item in results if item["passed"])
    print(f"通过: {passed}/{len(results)}")
    print(f"结果文件: {output_path}")


if __name__ == "__main__":
    main()
