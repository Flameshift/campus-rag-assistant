# 学生手册 RAG 挑战集基线 v2

- 基线日期：2026-09-16
- 上一版基线：v1 挑战集（95.0%）
- 评估集：`eval/student_handbook_challenging_questions.jsonl`，40 题
- 运行方式：单次完整运行，4 路并发，无超时合并

## 评估指标

| 指标 | 数值 | 相比 v1 |
| --- | ---: | ---: |
| 题目总数 | 40 | - |
| 完全正确 | 40（100.0%） | +2 题 |
| 部分正确 | 0 | -1 题 |
| 错误 | 0 | -1 题 |
| 无答案正确拒答 | 6 / 6 | 持平 |
| 带行内证据编号 | 40 / 40 | 持平 |
| 带末尾来源列表 | 40 / 40 | 持平 |
| 平均延迟 | 100.09 秒 | +6.85 秒 |
| 接口错误 | 0 | 持平 |

## 分题型结果

| 类型 | 数量 | 完全正确 | 平均分 |
| --- | ---: | ---: | ---: |
| colloquial | 5 | 5 | 2.00 |
| verbose | 5 | 5 | 2.00 |
| ambiguous_reference | 5 | 5 | 2.00 |
| typo_no_punctuation | 5 | 5 | 2.00 |
| false_premise | 5 | 5 | 2.00 |
| mixed_intent | 5 | 5 | 2.00 |
| unanswerable | 5 | 5 | 2.00 |
| prompt_injection | 5 | 5 | 2.00 |

## 数据文件

- 原始结果：`eval/results/run_20260916_220356.jsonl`
- 语义评分结果：`eval/results/run_20260916_220356_judged.jsonl`
- 语义评判报告：`eval/results/run_20260916_220356_judge_report.md`
- 与 v1 对比：`eval/results/run_20260916_220356_judged_vs_v1.md`
