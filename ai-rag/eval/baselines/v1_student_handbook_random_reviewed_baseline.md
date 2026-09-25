# 学生手册 RAG 基线 v1（随机复核集）

- 基线日期：2026-09-19
- 对照基线：常规集 v7、挑战集 v2
- 数据集：140 道随机候选，复核后保留并验证
- 数据集标识：`random-test-v1-reviewed`
- 回答模型：`deepseek-flash`
- 评判模型：`deepseek-chat`
- 精排模型：`qwen3.7-text-rerank`

本基线用于观察未经定向编写的随机样本，不与常规集和挑战集直接比较准确率。三套数据集的题型分布和难度不同。

## 评估指标

| 指标 | 数值 |
| --- | ---: |
| 题目总数 | 140 |
| 完全正确 | 134（95.7%） |
| 部分正确 | 4（2.9%） |
| 错误 | 2（1.4%） |
| Judge 平均分 | 1.943 / 2 |
| 无答案正确拒答 | 15 / 15 |
| 接口错误 | 0 |
| Judge 请求错误 | 0 |
| 平均来源数 | 8.89 |
| 真值分块召回率 | 95.6% |
| 上下文关键事实覆盖率 | 58.9% |
| Rerank Top-1 平均分 | 0.8960 |
| 父级扩展命中率 | 30.7% |
| 引用覆盖率 | 65.6% |
| 引用编号有效率 | 96.4% |
| Claim 支持率 | 90.1% |
| 回答补全触发率 | 8.6% |
| 平均延迟 | 89.76 秒 |
| P50 / P95 延迟 | 88.13 / 102.01 秒 |

延迟主要来自外部 Embedding 和 Rerank 服务，且本轮使用 6 路并发，不作为生产性能基线。

## 分题型结果

| 类型 | 数量 | 完全正确 | 部分正确 | 错误 | 平均分 |
| --- | ---: | ---: | ---: | ---: | ---: |
| ambiguous_reference | 8 | 8 | 0 | 0 | 2.000 |
| colloquial | 15 | 14 | 0 | 1 | 1.867 |
| comparison | 1 | 1 | 0 | 0 | 2.000 |
| fact | 11 | 11 | 0 | 0 | 2.000 |
| false_premise | 16 | 16 | 0 | 0 | 2.000 |
| mixed_intent | 14 | 12 | 2 | 0 | 1.857 |
| multi_hop | 11 | 9 | 1 | 1 | 1.727 |
| procedure | 7 | 7 | 0 | 0 | 2.000 |
| prompt_injection | 10 | 9 | 1 | 0 | 1.900 |
| table | 9 | 9 | 0 | 0 | 2.000 |
| typo_no_punctuation | 16 | 16 | 0 | 0 | 2.000 |
| unanswerable | 15 | 15 | 0 | 0 | 2.000 |
| verbose | 7 | 7 | 0 | 0 | 2.000 |

## 阶段耗时

| 阶段 | 平均耗时 |
| --- | ---: |
| Query Embedding | 42.00 秒 |
| 整体检索 | 42.08 秒 |
| Rerank | 40.32 秒 |
| 父级扩展 | 52.06 毫秒 |
| 相邻扩展 | 27.79 毫秒 |
| 回答复核 | 1.28 秒 |
| LLM 生成 | 5.83 秒 |
| 端到端请求 | 89.69 秒 |

## 失败与题目问题

真正落在回答层的错误：

- `gen-colloquial-0228`：把综合素质评价总分 100 分误当成德育 F1 满分。
- `gen-multi_hop-0184`：正确证据已进入候选，但回答选择了错误的废止文件。

检索或查询改写导致的部分正确：

- `gen-multi_hop-0262`：遗漏依据文件的适用范围。
- `gen-mixed_intent-0220`：资助目的命中了相近但不同的条款。

题目自包含性不足：

- `gen-mixed_intent-0012`：问题没有指明“本办法”对应哪份文件。
- `gen-prompt_injection-0234`：问题没有指明“第一条”属于哪项制度。

以上题目问题已保留在本基线中，后续如果修订数据集，应升级为 `random-test-v2` 并重跑全部基线。

## 数据文件

- 数据集：`eval/generated/random_test_v1/random_test_v1_reviewed.jsonl`
- 数据集清单：`eval/generated/random_test_v1/manifest_reviewed.json`
- 原始结果：`eval/results/run_20260919_153517.jsonl`
- 语义评分结果：`eval/results/run_20260919_153517_judged.jsonl`
- 语义评判报告：`eval/results/run_20260919_153517_judge_report.md`
- 分层指标 JSON：`eval/reports/layer_metrics_20260919_161532.json`
- 分层指标报告：`eval/reports/layer_metrics_20260919_161532.md`
