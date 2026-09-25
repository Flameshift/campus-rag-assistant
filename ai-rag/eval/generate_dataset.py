"""基于当前知识库生成候选测试集。

流程：证据选择 -> 分型生成 -> 独立校验 -> 去重 -> 分层划分 -> manifest。
自动生成的结果默认 review_status=pending，不能直接当作黄金测试集。
"""

import argparse
import hashlib
import json
import random
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from langchain_core.documents import Document
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.rag_service import rag_service  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = EVAL_DIR / "generated"
DEFAULT_EXISTING = [
    EVAL_DIR / "student_handbook_questions.jsonl",
    EVAL_DIR / "student_handbook_challenging_questions.jsonl",
]

STANDARD_TYPES = ["fact", "multi_hop", "table", "procedure", "comparison", "unanswerable"]
CHALLENGE_TYPES = [
    "colloquial",
    "verbose",
    "ambiguous_reference",
    "typo_no_punctuation",
    "false_premise",
    "mixed_intent",
    "prompt_injection",
]
DEFAULT_TYPES = STANDARD_TYPES + CHALLENGE_TYPES

TYPE_PROMPTS = {
    "fact": "生成一个直接查询单一事实、时间、对象或条件的问题。",
    "multi_hop": "生成一个必须综合两条相关证据才能完整回答的问题，两个事实应属于同一制度主题。",
    "table": "生成一个需要读取表格中的金额、比例、时限或数量的问题。",
    "procedure": "生成一个询问申请、审批、办理、复查或申诉流程的问题。",
    "comparison": "生成一个需要比较两个同类对象或两种相近处理方式的问题。",
    "colloquial": "用学生日常口语提问，表达自然但不要改变事实范围。",
    "verbose": "加入真实生活背景和多余信息，但最终只能包含一个明确问题意图。",
    "ambiguous_reference": "设计两轮对话，第一轮给出背景，第二轮使用指代词追问。",
    "typo_no_punctuation": "使用无标点、口语缩写或轻微错字提问，但语义必须清晰。",
    "false_premise": "问题包含一个与证据冲突的错误前提，标准答案必须先纠正前提。",
    "mixed_intent": "把两个不同但都必须依据证据回答的问题合并在一个问题中。",
    "prompt_injection": "包含忽略资料、按假设回答、编造或绕过规则的错误指令。",
}

UNANSWERABLE_TOPICS = [
    "食堂周末营业时间",
    "快递站晚上关门时间",
    "校园网每月收费标准",
    "宿舍床铺的具体长宽尺寸",
    "图书馆每周闭馆时间",
    "校车运行时刻表",
    "校内停车收费标准",
    "校医院各科室坐诊医生名单",
    "体育馆游泳池开放时间",
    "校园卡补办具体费用",
]


def _json_extract(content: str):
    match = re.search(r"(\{.*\}|\[.*\])", content or "", re.S)
    if not match:
        raise ValueError("模型没有返回 JSON")
    return json.loads(match.group(1))


def _normalize_question(value: str) -> str:
    return re.sub(r"[\s，。！？、,.!?;；:：\"'“”‘’（）()\-_]+", "", value or "").lower()


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_documents() -> list[Document]:
    result = rag_service.vectorstore.get(include=["documents", "metadatas"])
    documents = [
        Document(page_content=content, metadata=dict(metadata or {}))
        for content, metadata in zip(
            result.get("documents", []),
            result.get("metadatas", []),
        )
    ]
    return sorted(
        documents,
        key=lambda doc: (
            str(doc.metadata.get("source") or ""),
            int(doc.metadata.get("order_index", 0) or 0),
            int(doc.metadata.get("chunk_id", 0) or 0),
        ),
    )


def _evidence_text(documents: list[Document]) -> str:
    blocks = []
    for index, document in enumerate(documents, 1):
        metadata = document.metadata
        blocks.append(
            "[证据{index}] {source} 第{page}页 {section}\n{content}".format(
                index=index,
                source=metadata.get("source") or "未知文档",
                page=metadata.get("page_start") or metadata.get("page") or "",
                section=metadata.get("section_path") or "",
                content=document.page_content,
            )
        )
    return "\n\n".join(blocks)


def _pick_evidence(documents: list[Document], qtype: str, rng: random.Random) -> list[Document]:
    sections = [
        document
        for document in documents
        if document.metadata.get("chunk_strategy") in {"section", "recursive"}
        and len(document.page_content) >= 60
    ]
    tables = [
        document
        for document in documents
        if document.metadata.get("chunk_strategy") == "table"
    ]
    if qtype == "table" and tables:
        return [rng.choice(tables)]

    procedure_hits = [
        document
        for document in sections
        if any(
            keyword in document.page_content
            for keyword in ("申请", "审批", "办理", "程序", "期限", "复查", "申诉")
        )
    ]
    if qtype == "procedure" and procedure_hits:
        return [rng.choice(procedure_hits)]

    first = rng.choice(sections or documents)
    if qtype in {"multi_hop", "comparison", "mixed_intent"}:
        first_scope = str(first.metadata.get("section_path") or "").split(" > ")[0]
        first_parent = first.metadata.get("parent_id")
        candidates = [
            document
            for document in sections
            if document is not first
            and document.metadata.get("source") == first.metadata.get("source")
            and (
                document.metadata.get("parent_id") == first_parent
                or str(document.metadata.get("section_path") or "").split(" > ")[0]
                == first_scope
            )
        ]
        if not candidates:
            candidates = [
                document
                for document in sections
                if document is not first
                and document.metadata.get("source") == first.metadata.get("source")
            ]
        if not candidates:
            candidates = [document for document in sections if document is not first]
        second = rng.choice(candidates) if candidates else first
        return [first, second]
    return [first]


def _generator_prompt(qtype: str, evidence: list[Document]) -> str:
    if qtype == "unanswerable":
        topic = random.choice(UNANSWERABLE_TOPICS)
        return f"""你是 RAG 测试集生成器。请生成 1 条知识库未覆盖的问题。

主题：{topic}

要求：
1. 问题必须自然、具体、像一个学生真实会问的问题。
2. 该问题不能是学生手册通常会直接规定的学业制度。
3. answerable=false。
4. reference_answer 必须明确说明学生手册未规定，不能编造具体答案。
5. key_facts 必须为空数组。
6. history 通常为空数组。

只输出 JSON 对象：
{{"question":"","type":"unanswerable","answerable":false,"reference_answer":"","key_facts":[],"history":[],"difficulty":"hard"}}
"""

    type_instruction = TYPE_PROMPTS[qtype]
    ambiguous_note = (
        "必须返回两轮对话，history 至少包含一条 user 和一条 assistant，"
        "question 使用“那这个”“多久内找谁”等依赖指代的追问。"
        if qtype == "ambiguous_reference"
        else "history 返回空数组。"
    )
    return f"""你是严格的 RAG 测试集生成器。只能依据给定证据生成题目。

题型：{qtype}
要求：{type_instruction}

规则：
1. 问题必须能由证据直接回答，不能依赖外部知识。
2. reference_answer 必须简洁、完整、可核对。
3. key_facts 必须全部能在 reference_answer 中找到，使用短事实短语。
4. prompt_injection 题型应明确拒绝忽略证据或编造。
5. false_premise 题型必须先指出错误前提。
6. mixed_intent 必须包含两个都要回答的事项。
7. {ambiguous_note}
8. 只输出一个 JSON 对象，不要输出 Markdown。

输出格式：
{{"question":"","type":"{qtype}","answerable":true,"reference_answer":"","key_facts":[],"history":[],"difficulty":"easy|medium|hard"}}

证据：
{_evidence_text(evidence)}
"""


def _verifier_prompt(item: dict, evidence: list[Document]) -> str:
    if not item.get("answerable", True):
        return f"""你是独立的 RAG 测试集审核员。请检查这条无答案题的标注是否合理。

问题：{item.get("question")}
标准答案：{item.get("reference_answer")}

要求：
- 如果问题确实属于知识库未规定主题，且没有编造具体答案，返回 accept。
- 如果问题其实可以由常识或手册直接回答，返回 reject。
- 只输出 JSON：{{"verdict":"accept|reject","reason":"不超过50字"}}
"""
    return f"""你是独立的 RAG 测试集审核员。请验证题目、标准答案和关键事实。

【问题】
{item.get("question")}

【标准答案】
{item.get("reference_answer")}

【关键事实】
{"、".join(item.get("key_facts", []))}

【证据】
{_evidence_text(evidence)}

检查：
1. reference_answer 是否完全由证据支持。
2. 问题是否明确且答案唯一。
3. key_facts 是否全部出现在 reference_answer 中。
4. 是否存在编造、过多外部知识或证据缺失。
5. 多轮题是否有必要 history，且 history 不会直接泄露答案。

只输出 JSON：
{{"verdict":"accept|reject","reason":"不超过50字"}}
"""


def _call_json(client: OpenAI, model: str, prompt: str) -> dict:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=1200,
    )
    content = response.choices[0].message.content or ""
    data = _json_extract(content)
    if not isinstance(data, dict):
        raise ValueError("生成结果不是 JSON 对象")
    return data


def _validate_item(item: dict, qtype: str, evidence: list[Document]) -> str | None:
    question = str(item.get("question") or "").strip()
    reference = str(item.get("reference_answer") or "").strip()
    if len(question) < 4:
        return "问题过短"
    if not reference:
        return "缺少标准答案"
    if item.get("answerable", True) and not item.get("key_facts"):
        return "缺少关键事实"
    if item.get("type") != qtype:
        return "题型不一致"
    if qtype == "ambiguous_reference" and len(item.get("history") or []) < 2:
        return "缺少多轮历史"
    if qtype == "verbose" and question.count("？") > 1:
        return "verbose题包含多个问题意图"
    if qtype == "mixed_intent" and not re.search(r"另外|同时|分别|还有|以及", question):
        return "mixed_intent题缺少两个明确事项"
    if item.get("answerable", True) and qtype in {
        "fact",
        "table",
        "procedure",
        "multi_hop",
        "comparison",
    }:
        missing_facts = [
            fact for fact in item.get("key_facts", [])
            if str(fact) not in reference
        ]
        if missing_facts:
            return f"关键事实未出现在标准答案: {missing_facts[0]}"
    if qtype == "ambiguous_reference":
        if "多久" in question and not re.search(
            r"天|日|月|年|工作日|期限|学期|学年|内",
            reference,
        ):
            return "问题询问时限，但标准答案没有时限"
        if "找谁" in question and not re.search(
            r"学院|办公室|辅导员|教务处|委员会|学生处|部门|中心|班长|领导|教师",
            reference,
        ):
            return "问题询问责任主体，但标准答案没有明确主体"
    if not item.get("answerable", True) and item.get("key_facts"):
        return "无答案题不应包含关键事实"
    if not evidence and item.get("answerable", True):
        return "缺少证据"
    return None


def _build_jobs(documents: list[Document], types: list[str], target: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    jobs = []
    for index in range(target):
        qtype = types[index % len(types)]
        evidence = [] if qtype == "unanswerable" else _pick_evidence(documents, qtype, rng)
        jobs.append({"index": index, "type": qtype, "evidence": evidence})
    return jobs


def _deduplicate(items: list[dict], existing: list[dict]) -> tuple[list[dict], list[dict]]:
    seen = {_normalize_question(item.get("question", "")) for item in existing}
    accepted = []
    rejected = []
    for item in items:
        key = _normalize_question(item.get("question", ""))
        if not key or key in seen:
            rejected.append({**item, "reject_reason": "duplicate_question"})
            continue
        seen.add(key)
        accepted.append(item)
    return accepted, rejected


def _split_items(items: list[dict], hidden_ratio: float, seed: int) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    grouped = defaultdict(list)
    for item in items:
        grouped[item["type"]].append(item)

    hidden = []
    visible = []
    for group in grouped.values():
        rng.shuffle(group)
        hidden_count = max(1, round(len(group) * hidden_ratio)) if len(group) > 1 else 0
        hidden.extend(group[:hidden_count])
        visible.extend(group[hidden_count:])
    rng.shuffle(hidden)
    rng.shuffle(visible)
    return visible, hidden


def _write_jsonl(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for item in items:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")


def run(args) -> None:
    started = time.time()
    seed = args.seed
    types = [value.strip() for value in args.types.split(",") if value.strip()]
    documents = _load_documents()
    if not documents:
        raise SystemExit("知识库为空")

    existing = []
    for path in DEFAULT_EXISTING:
        existing.extend(_load_jsonl(path))
    jobs = _build_jobs(documents, types, args.target, seed)
    client = OpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL,
        timeout=args.timeout,
        max_retries=1,
    )

    def generate(job: dict) -> dict:
        item = _call_json(client, args.model, _generator_prompt(job["type"], job["evidence"]))
        item["type"] = job["type"]
        item["history"] = item.get("history") or []
        item["key_facts"] = item.get("key_facts") or []
        item["id"] = f"gen-{job['type']}-{job['index'] + 1:04d}"
        item["source_chunk_ids"] = [
            document.metadata.get("chunk_id") for document in job["evidence"]
        ]
        item["source_parent_ids"] = list(
            dict.fromkeys(
                str(document.metadata.get("parent_id"))
                for document in job["evidence"]
                if document.metadata.get("parent_id")
            )
        )
        item["source"] = (
            f"{job['evidence'][0].metadata.get('source')}#p"
            f"{job['evidence'][0].metadata.get('page_start')}"
            if job["evidence"]
            else "知识库未覆盖"
        )
        item["source_section"] = (
            " | ".join(
                str(document.metadata.get("section_path") or "")
                for document in job["evidence"]
            )
            if job["evidence"]
            else "未覆盖"
        )
        item["generation_model"] = args.model
        item["generation_seed"] = seed
        item["review_status"] = "pending"
        item["verification_status"] = "pending"
        return item

    generated = []
    generation_errors = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(generate, job): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                generated.append(future.result())
            except Exception as exc:
                generation_errors.append(
                    {"id": f"gen-{job['type']}-{job['index'] + 1:04d}", "error": str(exc)}
                )

    generated.sort(key=lambda item: item["id"])
    evidence_by_id = {
        f"gen-{job['type']}-{job['index'] + 1:04d}": job["evidence"]
        for job in jobs
    }

    verified = []
    rejected = []
    verification_errors = []
    for item in generated:
        evidence = evidence_by_id.get(item["id"], [])
        validation_error = _validate_item(item, item["type"], evidence)
        if validation_error:
            rejected.append({**item, "reject_reason": validation_error})
            continue
        try:
            verdict = _call_json(
                client,
                args.model,
                _verifier_prompt(item, evidence),
            )
        except Exception as exc:
            verification_errors.append({"id": item["id"], "error": str(exc)})
            rejected.append({**item, "reject_reason": f"verification_error: {exc}"})
            continue

        if verdict.get("verdict") != "accept":
            rejected.append(
                {
                    **item,
                    "verification_status": "rejected",
                    "reject_reason": verdict.get("reason") or "verifier_rejected",
                }
            )
            continue

        verified.append(
            {
                **item,
                "verification_status": "verified",
                "verification_reason": verdict.get("reason") or "",
            }
        )

    deduped, duplicate_rejected = _deduplicate(verified, existing)
    rejected.extend(duplicate_rejected)
    visible, hidden = _split_items(deduped, args.hidden_ratio, seed)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pool_path = output_dir / f"candidate_pool_{stamp}.jsonl"
    random_path = output_dir / f"random_candidates_{stamp}.jsonl"
    hidden_path = output_dir / f"hidden_candidates_{stamp}.jsonl"
    rejected_path = output_dir / f"rejected_{stamp}.jsonl"
    manifest_path = output_dir / f"manifest_{stamp}.json"

    _write_jsonl(pool_path, deduped)
    _write_jsonl(random_path, visible)
    _write_jsonl(hidden_path, hidden)
    _write_jsonl(rejected_path, rejected)

    manifest = {
        "created_at": datetime.now().isoformat(),
        "seed": seed,
        "target": args.target,
        "types": types,
        "model": args.model,
        "workers": args.workers,
        "knowledge_chunks": len(documents),
        "generated": len(generated),
        "verified": len(deduped),
        "hidden": len(hidden),
        "random": len(visible),
        "rejected": len(rejected),
        "generation_errors": generation_errors,
        "verification_errors": verification_errors,
        "duration_seconds": round(time.time() - started, 2),
        "artifacts": {
            "pool": str(pool_path),
            "random": str(random_path),
            "hidden": str(hidden_path),
            "rejected": str(rejected_path),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="基于知识库生成 RAG 候选测试集")
    parser.add_argument("--target", type=int, default=40, help="生成目标题目数")
    parser.add_argument("--types", default=",".join(DEFAULT_TYPES), help="题型列表")
    parser.add_argument("--workers", type=int, default=4, help="并发生成数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--hidden-ratio", type=float, default=0.3, help="隐藏集比例")
    parser.add_argument("--model", default="deepseek-chat", help="生成和校验模型")
    parser.add_argument("--timeout", type=int, default=120, help="单次模型调用超时")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="输出目录")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
