"""把新一轮评估结果与基线对比。

用法：
    python eval/compare_baseline.py --judged eval/results/<new_run>_judged.jsonl
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_BASELINE = EVAL_DIR / "baselines" / "v7_student_handbook_parent_child_baseline.json"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarize(items: list[dict]) -> dict:
    total = len(items)
    correct = sum(1 for item in items if item["judge_score"] == 2)
    partial = sum(1 for item in items if item["judge_score"] == 1)
    wrong = sum(1 for item in items if item["judge_score"] == 0)
    unanswerable = [item for item in items if not item["answerable"]]
    refusal_ok = sum(1 for item in unanswerable if item["judge_score"] == 2)
    by_type = defaultdict(list)
    for item in items:
        by_type[item["type"]].append(item["judge_score"])
    return {
        "total": total,
        "correct": correct,
        "correct_rate": correct / total if total else 0,
        "partial": partial,
        "wrong": wrong,
        "refusal_ok": refusal_ok,
        "unanswerable": len(unanswerable),
        "avg_latency": sum(item.get("latency_seconds", 0) for item in items) / total if total else 0,
        "by_type": {
            name: {
                "count": len(scores),
                "correct": sum(1 for score in scores if score == 2),
                "avg_score": sum(scores) / len(scores) if scores else 0,
            }
            for name, scores in by_type.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="与评估基线对比")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="基线 JSON 路径")
    parser.add_argument("--judged", required=True, help="新结果 judged JSONL 路径")
    args = parser.parse_args()

    baseline_path = Path(args.baseline)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    judged_path = Path(args.judged)
    current = summarize(load_jsonl(judged_path))
    base_metrics = baseline["metrics"]
    baseline_unanswerable_total = base_metrics.get(
        "unanswerable_total",
        baseline.get("dataset", {}).get("unanswerable", 0),
    )
    baseline_avg_latency = base_metrics.get("avg_latency_seconds")
    if baseline_avg_latency is None:
        baseline_avg_latency = base_metrics.get("latency_p50_seconds", 0.0)
        baseline_latency_label = "P50"
    else:
        baseline_latency_label = "平均"

    def delta(new, old):
        return new - old

    lines = [
        f"# 与基线 {baseline['baseline_id']} 对比",
        "",
        f"- 对比文件：`{judged_path.name}`",
        f"- 基线日期：{baseline['created_at']}",
        "",
        "## 总体指标",
        "",
        "| 指标 | 基线 | 本次 | 变化 |",
        "| --- | --- | --- | --- |",
        f"| 完全正确率 | {base_metrics['correct_rate']:.1%} | {current['correct_rate']:.1%} | {delta(current['correct_rate'], base_metrics['correct_rate']):+.1%} |",
        f"| 完全正确数 | {base_metrics['correct']} | {current['correct']} | {current['correct'] - base_metrics['correct']:+d} |",
        f"| 部分正确数 | {base_metrics['partial']} | {current['partial']} | {current['partial'] - base_metrics['partial']:+d} |",
        f"| 错误数 | {base_metrics['wrong']} | {current['wrong']} | {current['wrong'] - base_metrics['wrong']:+d} |",
        f"| 无答案正确拒答 | {base_metrics['unanswerable_correct_refusal']}/{baseline_unanswerable_total} | {current['refusal_ok']}/{current['unanswerable']} | {current['refusal_ok'] - base_metrics['unanswerable_correct_refusal']:+d} |",
        f"| 延迟（基线{baseline_latency_label}） | {baseline_avg_latency:.2f}s | {current['avg_latency']:.2f}s | {current['avg_latency'] - baseline_avg_latency:+.2f}s |",
        "",
        "## 分题型对比",
        "",
        "| 类型 | 基线平均分 | 本次平均分 | 变化 |",
        "| --- | --- | --- | --- |",
    ]
    for type_name, base_type in baseline.get("by_type", {}).items():
        current_type = current["by_type"].get(type_name)
        if not current_type:
            continue
        lines.append(
            f"| {type_name} | {base_type['avg_score']:.3f} | {current_type['avg_score']:.3f} | "
            f"{current_type['avg_score'] - base_type['avg_score']:+.3f} |"
        )

    baseline_tag = baseline["baseline_id"].split("-")[0]
    output_path = judged_path.with_name(judged_path.stem + f"_vs_{baseline_tag}.md")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n对比报告: {output_path}")


if __name__ == "__main__":
    main()
