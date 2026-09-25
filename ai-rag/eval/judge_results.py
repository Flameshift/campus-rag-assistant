"""对评估结果做语义评判（LLM-as-Judge）。

读取 eval_runner.py 生成的回答结果，用大模型按统一 rubric 打分：
    2 = 完全正确
    1 = 部分正确 / 遗漏关键事实
    0 = 错误、编造或答非所问

用法：
    python eval/judge_results.py eval/results/run_YYYYMMDD_HHMMSS.jsonl
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402

JUDGE_PROMPT = """你是严格的 RAG 评测员，请判断【模型回答】是否正确。

评分规则：
- 2 分：完全正确，关键事实齐全，没有编造。
- 1 分：部分正确，遗漏部分关键事实或表述不完整。
- 0 分：错误、编造、答非所问。

判断要求：
- 只依据【标准答案】和【关键事实】，不要引入外部知识。
- 允许同义表达、加粗符号、空格和标点差异。
- 标准答案未逐字列出的补充细节，不得仅因“额外”而扣分；只有与标准答案冲突、遗漏关键事实，或明显脱离问题并编造时才降分。
- 必须逐项检查【关键事实】，key_fact_results 的顺序和数量必须与【关键事实】一致。
- missing_key_facts 只列出回答中确实缺少的关键事实原文；全部存在时必须是空数组。
- 如果【是否可回答】为 false，模型明确说明资料中没有相关信息、无法确定或无法根据现有资料回答，refusal_correct=true。

只输出 JSON，不要输出其他内容：
{{"key_fact_results":[{{"fact":"关键事实","present":true}}],"missing_key_facts":[],"contradiction":false,"off_topic":false,"refusal_correct":false,"reason":"不超过50字的理由"}}

【问题】
{question}

【是否可回答】
{answerable}

【对话历史】
{history}

【标准答案】
{reference_answer}

【关键事实】
{key_facts}

【模型回答】
{answer}
"""


def judge(client: OpenAI, item: dict, model: str) -> dict:
    history = item.get("history") or []
    history_text = "\n".join(
        f"{message.get('role', '')}: {message.get('content', '')}"
        for message in history
    ) or "（无）"
    prompt = JUDGE_PROMPT.format(
        question=item["question"],
        answerable=item["answerable"],
        history=history_text,
        reference_answer=item["reference_answer"],
        key_facts="、".join(item.get("key_facts", [])) or "无",
        answer=item.get("answer", ""),
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        # deepseek-flash 会先产生 reasoning_content，token 太小会导致正文为空。
        max_tokens=2048,
    )
    message = response.choices[0].message
    # 正文为空时回退到推理内容，避免推理型模型返回空 content。
    content = message.content or getattr(message, "reasoning_content", "") or ""
    match = re.search(r"\{.*\}", content, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            return {
                "score": derive_score(item, data),
                "reason": str(data.get("reason", "")),
                "key_fact_results": data.get("key_fact_results") or [],
                "missing_key_facts": data.get("missing_key_facts") or [],
                "contradiction": bool(data.get("contradiction")),
                "off_topic": bool(data.get("off_topic")),
                "refusal_correct": bool(data.get("refusal_correct")),
            }
        except (ValueError, TypeError):
            pass
    return {"score": 0, "reason": f"评判输出无法解析: {content[:80]}"}


def derive_score(item: dict, data: dict) -> int:
    """根据逐项关键事实结果推导最终分数。"""
    if not item.get("answerable", True):
        return 2 if bool(data.get("refusal_correct")) else 0
    if bool(data.get("contradiction")) or bool(data.get("off_topic")):
        return 0

    facts = item.get("key_facts", [])
    results = data.get("key_fact_results") or []
    missing = data.get("missing_key_facts") or []
    if missing:
        return 1

    if any(
        not isinstance(result, dict) or not bool(result.get("present"))
        for result in results
    ):
        return 1

    # 允许 Judge 合并同义关键事实，只要它明确返回“无缺失”且没有 present=false。
    if facts and not results and not missing:
        return 1
    return 2


def main() -> None:
    parser = argparse.ArgumentParser(description="对评估结果做 LLM-as-Judge 语义评分")
    parser.add_argument("result", help="eval_runner.py 生成的结果 JSONL")
    parser.add_argument(
        "--model",
        default="deepseek-chat",
        help="评判模型，默认 deepseek-chat（推理型模型容易输出空 content）",
    )
    args = parser.parse_args()

    result_path = Path(args.result)
    items = [
        json.loads(line)
        for line in result_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    client = OpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL,
        timeout=60,
        max_retries=1,
    )

    judged = []
    for index, item in enumerate(items, start=1):
        try:
            verdict = judge(client, item, args.model)
            error = ""
        except Exception as exc:
            verdict = {"score": 0, "reason": f"评判请求失败: {exc}"}
            error = str(exc)
        judged.append(
            {
                **item,
                "judge_score": verdict["score"],
                "judge_reason": verdict["reason"],
                "judge_key_fact_results": verdict.get("key_fact_results", []),
                "judge_missing_key_facts": verdict.get("missing_key_facts", []),
                "judge_contradiction": verdict.get("contradiction", False),
                "judge_off_topic": verdict.get("off_topic", False),
                "judge_refusal_correct": verdict.get("refusal_correct", False),
                "judge_error": error,
            }
        )
        print(f"[{index}/{len(items)}] {item['id']} score={verdict['score']} {verdict['reason'][:40]}")

    output_path = result_path.with_name(result_path.stem + "_judged.jsonl")
    with output_path.open("w", encoding="utf-8") as stream:
        for item in judged:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")

    by_type = defaultdict(list)
    for item in judged:
        by_type[item["type"]].append(item["judge_score"])

    total = len(judged)
    correct = sum(1 for item in judged if item["judge_score"] == 2)
    partial = sum(1 for item in judged if item["judge_score"] == 1)
    wrong = sum(1 for item in judged if item["judge_score"] == 0)
    unanswerable = [item for item in judged if not item["answerable"]]
    refusal_ok = sum(1 for item in unanswerable if item["judge_score"] == 2)

    lines = [
        "# LLM-as-Judge 评估报告",
        "",
        f"- 结果文件：`{result_path.name}`",
        f"- 题目总数：{total}",
        f"- 完全正确（2分）：{correct} ({correct / total:.1%})",
        f"- 部分正确（1分）：{partial} ({partial / total:.1%})",
        f"- 错误（0分）：{wrong} ({wrong / total:.1%})",
        f"- 无答案题正确拒答：{refusal_ok}/{len(unanswerable)}",
        f"- 平均延迟：{sum(item.get('latency_seconds', 0) for item in judged) / total:.2f}s",
        "",
        "## 分题型得分",
        "",
        "| 类型 | 题数 | 完全正确 | 平均分 |",
        "| --- | --- | --- | --- |",
    ]
    for type_name, scores in sorted(by_type.items(), key=lambda pair: -len(pair[1])):
        lines.append(
            f"| {type_name} | {len(scores)} | {sum(1 for s in scores if s == 2)} | {sum(scores) / len(scores):.2f} |"
        )

    lines += ["", "## 错误和部分正确题目", ""]
    for item in judged:
        if item["judge_score"] >= 2:
            continue
        answer = (item.get("answer") or "").replace("\n", " ")[:200]
        lines.append(f"### {item['id']} score={item['judge_score']} {item['question']}")
        lines.append("")
        lines.append(f"- 评判理由：{item['judge_reason']}")
        lines.append(f"- 标准答案：{item['reference_answer']}")
        lines.append(f"- 回答摘要：{answer}")
        lines.append("")

    report_path = result_path.with_name(result_path.stem + "_judge_report.md")
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n===== 语义评判汇总 =====")
    print(f"完全正确: {correct}/{total} = {correct / total:.1%}")
    print(f"部分正确: {partial}/{total}")
    print(f"错误: {wrong}/{total}")
    print(f"无答案题正确拒答: {refusal_ok}/{len(unanswerable)}")
    print(f"结果文件: {output_path}")
    print(f"报告文件: {report_path}")


if __name__ == "__main__":
    main()
