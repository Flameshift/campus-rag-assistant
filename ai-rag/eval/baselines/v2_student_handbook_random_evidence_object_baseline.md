# 学生手册 RAG 基线 v2（随机复核集 + Evidence Object）

- 基线日期：2026-09-19
- 数据集：`random-test-v2`，共 140 题
- 配置：Evidence Object 开启，条件式父级/相邻扩展关闭
- 对照：随机复核集 v1 控制实验

## 评估指标

| 指标 | 数值 |
| --- | ---: |
| 完全正确 | 134 / 140，95.7% |
| 部分正确 | 5 |
| 错误 | 1 |
| Judge 平均分 | 1.950 |
| 无答案正确拒答 | 15 / 15 |
| 平均来源数 | 8.24 |
| 完整上下文召回率 | 97.2% |
| Recall@3 | 91.6% |
| Precision@3 | 35.47% |
| Hit@3 | 96.8% |
| MRR | 0.8987 |
| 上下文关键事实覆盖率 | 59.22% |
| Claim 支持率 | 92.25% |
| 引用覆盖率 | 63.59% |
| 引用编号有效率 | 95.71% |
| 平均候选 Token | 3478.87 |
| 平均最终上下文 Token | 1747.79 |
| 上下文压缩率 | 51.18% |

## 结论

Evidence Object 单独开启后，平均来源数从 9.47 降到 8.24，完整上下文召回率从
95.6% 提升到 97.2%，Recall@3 从 91.2% 提升到 91.6%，答案正确数从 133 提升到
134。条件式扩展会导致召回下降，因此继续保持关闭。

本轮外部模型服务响应速度明显快于此前实验，P50/P95 延迟不作为生产性能基线。

## 数据文件

- 数据集：`eval/generated/random_test_v2/random_test_v2.jsonl`
- 原始结果：`eval/results/experiments/B1_full/run_20260919_200243.jsonl`
- Judge 结果：`eval/results/experiments/B1_full/run_20260919_200243_judged.jsonl`
- Judge 报告：`eval/results/experiments/B1_full/run_20260919_200243_judge_report.md`
- 分层指标：`eval/reports/experiments/B1_full/layer_metrics_20260919_200813.md`
