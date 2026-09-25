"""根据评估结果生成 Markdown 报告。

用法：
    python eval/analyze_results.py eval/results/run_YYYYMMDD_HHMMSS.jsonl
"""

import json
import sys
from collections import defaultdict
from pathlib import Path


def avg(values):
    return sum(values) / len(values) if values else 0.0


def main() -> None:
    result_path = Path(sys.argv[1])
    items = [
        json.loads(line)
        for line in result_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    answerable = [item for item in items if item["answerable"]]
    unanswerable = [item for item in items if not item["answerable"]]

    by_type = defaultdict(list)
    for item in answerable:
        by_type[item["type"]].append(item.get("fact_hit_rate") or 0)

    no_source = [item for item in answerable if item.get("source_count", 0) == 0]
    low_scores = [
        item for item in answerable if (item.get("fact_hit_rate") or 0) < 0.34
    ]
    refused = [item for item in unanswerable if item.get("refused")]
    missed_refusal = [item for item in unanswerable if not item.get("refused")]

    lines = [
        f"# 学生手册 RAG 评估报告",
        "",
        f"- 结果文件：`{result_path.name}`",
        f"- 题目总数：{len(items)}",
        f"- 有答案题目：{len(answerable)}",
        f"- 无答案题目：{len(unanswerable)}",
        f"- 平均关键事实覆盖率：{avg([(i.get('fact_hit_rate') or 0) for i in answerable]):.1%}",
        f"- 无答案拒答率：{len(refused)}/{len(unanswerable)} = {(len(refused) / len(unanswerable) if unanswerable else 0):.1%}",
        f"- 平均延迟：{avg([i.get('latency_seconds', 0) for i in items]):.2f}s",
        f"- 接口错误：{sum(1 for i in items if i.get('error'))}",
        "",
        "## 分题型表现",
        "",
        "| 类型 | 题数 | 平均关键事实覆盖率 |",
        "| --- | --- | --- |",
    ]
    for type_name, rates in sorted(by_type.items(), key=lambda pair: -len(pair[1])):
        lines.append(f"| {type_name} | {len(rates)} | {avg(rates):.1%} |")

    lines += [
        "",
        "## 检索为空",
        "",
        f"有答案题目中没有返回任何来源：{len(no_source)} 题",
        "",
    ]
    for item in no_source[:15]:
        lines.append(f"- `{item['id']}` {item['question']}")

    lines += [
        "",
        "## 低覆盖题目（关键事实覆盖率 < 34%）",
        "",
    ]
    for item in low_scores:
        answer = (item.get("answer") or "").replace("\n", " ")[:160]
        lines.append(f"### {item['id']} {item['question']}")
        lines.append("")
        lines.append(f"- 覆盖率：{item.get('fact_hit_rate'):.1%}")
        lines.append(f"- 命中关键事实：{item.get('fact_hits')}")
        lines.append(f"- 来源数量：{item.get('source_count')}")
        lines.append(f"- 回答摘要：{answer}")
        lines.append("")

    lines += [
        "## 无答案题处理",
        "",
    ]
    for item in unanswerable:
        answer = (item.get("answer") or "").replace("\n", " ")[:160]
        status = "正确拒答" if item.get("refused") else "疑似未拒答"
        lines.append(f"- `{item['id']}` {status}：{item['question']}")
        lines.append(f"  - 回答摘要：{answer}")

    lines += [
        "",
        "## 说明",
        "",
        "- 关键事实覆盖率基于字符串匹配，只能作为粗指标。",
        "- 覆盖率低不一定代表回答错误，可能是同义表达未被匹配。",
        "- 建议对低覆盖题目进行人工抽查或 LLM-as-Judge 复核。",
    ]

    report_path = result_path.with_name(result_path.stem + "_report.md")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(report_path)
    print(f"low_scores={len(low_scores)} no_source={len(no_source)} refusal={len(refused)}/{len(unanswerable)}")


if __name__ == "__main__":
    main()
