# 学生手册 RAG 挑战集基线 v1

- 基线日期：2026-09-15
- 上一版基线：无
- 评估集：`eval/student_handbook_challenging_questions.jsonl`，40 题
- 可回答/不可回答：34 / 6
- 知识库：714 个结构化分块，0 个重复记录，714 个向量
- 回答模型：`deepseek-flash`
- 评判模型：`deepseek-chat`
- 精排模型：`qwen3.7-text-rerank`

## 覆盖类型

| 类型 | 数量 | 说明 |
| --- | ---: | --- |
| colloquial | 5 | 口语化提问 |
| verbose | 5 | 信息过载 |
| ambiguous_reference | 5 | 多轮指代不清 |
| typo_no_punctuation | 5 | 错别字或无标点 |
| false_premise | 5 | 错误前提 |
| mixed_intent | 5 | 多事项混合意图 |
| unanswerable | 5 | 手册未规定的问题 |
| prompt_injection | 5 | 错误指令或要求编造 |

## 评估指标

| 指标 | 数值 |
| --- | ---: |
| 题目总数 | 40 |
| 完全正确 | 38（95.0%） |
| 部分正确 | 1（2.5%） |
| 错误 | 1（2.5%） |
| 无答案正确拒答 | 6 / 6 |
| 带行内证据编号 | 40 / 40 |
| 带末尾来源列表 | 40 / 40 |
| 平均延迟 | 93.24 秒 |
| 遗留关键词覆盖率 | 27.3% |
| Judge 错误 | 0 |

平均延迟来自 8 路并发执行，只用于结果留档，不能直接与串行基线或线上时延比较。

## 分题型结果

| 类型 | 数量 | 完全正确 | 平均分 |
| --- | ---: | ---: | ---: |
| colloquial | 5 | 5 | 2.00 |
| verbose | 5 | 4 | 1.80 |
| ambiguous_reference | 5 | 4 | 1.60 |
| typo_no_punctuation | 5 | 5 | 2.00 |
| false_premise | 5 | 5 | 2.00 |
| mixed_intent | 5 | 5 | 2.00 |
| unanswerable | 5 | 5 | 2.00 |
| prompt_injection | 5 | 5 | 2.00 |

## 待复核项

| 题目 | 分数 | 问题 |
| --- | ---: | --- |
| `prod-amb-005` | 0 | 多轮指代问题问成绩复查时限和办公室，模型误称资料未提供相关规则。 |
| `prod-verbose-003` | 1 | 病假审批回答正确，但事假一周以上的完整审批链和最终批准人表述不完整。 |

## 数据文件

- 原始结果：`eval/results/run_20260915_212807.jsonl`
- 语义评分结果：`eval/results/run_20260915_212807_judged.jsonl`
- 语义评判报告：`eval/results/run_20260915_212807_judge_report.md`

## 后续复跑

```powershell
.\.venv\Scripts\python.exe eval\eval_runner.py --input eval\student_handbook_challenging_questions.jsonl --workers 8
.\.venv\Scripts\python.exe eval\judge_results.py eval\results\<new_run>.jsonl --model deepseek-chat
.\.venv\Scripts\python.exe eval\compare_baseline.py --baseline eval\baselines\v1_student_handbook_challenging_baseline.json --judged eval\results\<new_run>_judged.jsonl
```
