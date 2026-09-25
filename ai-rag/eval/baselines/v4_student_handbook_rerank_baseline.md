# 学生手册 RAG 基线 v4（Rerank）

- 基线日期：2026-09-12
- 上一版基线：v3（BM25 + 向量 + 语义去重，96.1%）
- 知识库：278 个 canonical 分块，0 个重复记录，278 个向量
- 回答模型：`deepseek-flash`
- 评判模型：`deepseek-chat`
- 精排模型：`qwen3.7-text-rerank`

## Rerank 配置

```text
RETRIEVE_CANDIDATES = 20
RERANK_CANDIDATES = 20
TOP_K = 5
BM25_WEIGHT = 0.4
VECTOR_WEIGHT = 0.6
RERANK_API_KEY = EMBEDDING_API_KEY
```

处理链路：

```text
BM25 Top-20 + 向量 Top-20
        ↓ EnsembleRetriever 融合
最多 20 条 Rerank 候选
        ↓ qwen3.7-text-rerank
Top 5 进入回答模型上下文
```

Rerank 调用失败时自动回退融合检索原顺序，保证问答链路不被外部精排服务阻断。

## 评估指标

| 指标 | 数值 | 相比 v3 |
| --- | --- | --- |
| 题目总数 | 77 | - |
| 完全正确 | 74（96.1%） | 持平 |
| 部分正确 | 3 | 持平 |
| 错误 | 0 | 持平 |
| 无答案正确拒答 | 5 / 5 | 持平 |
| 平均延迟 | 4.21 秒 | -7.72 秒 |

平均延迟受外部模型接口波动影响较大，本轮延迟下降不能单独归因于 Rerank。

## 分题型结果

| 类型 | 数量 | 完全正确 | 平均分 |
| --- | ---: | ---: | ---: |
| fact | 42 | 42 | 2.000 |
| multi_hop | 13 | 11 | 1.846 |
| table | 10 | 10 | 2.000 |
| unanswerable | 5 | 5 | 2.000 |
| comparison | 4 | 4 | 2.000 |
| procedure | 3 | 2 | 1.667 |

## 剩余三道部分正确题目

| 题号 | 类型 | 原因 |
| --- | --- | --- |
| sh-028 | procedure | 遗漏“5日内答复是否受理”，复查时限表述不够准确 |
| sh-050 | multi_hop | 补充了标准答案未列出的条件，Judge 判定为部分正确 |
| sh-060 | multi_hop | 遗漏必修课专业前10%、综合考评班级前10% |

`sh-060` 的“前10%”条件位于 `chunk 258`。该分块没有进入向量或 BM25
的粗筛 Top-20，因此 Rerank 无法恢复。后续应优先处理分块边界和父子检索，
而不是继续增加精排候选数量。

## 数据文件

- 原始结果：`eval/results/run_20260912_213128.jsonl`
- 语义评分结果：`eval/results/run_20260912_213128_judged.jsonl`
- 语义评判报告：`eval/results/run_20260912_213128_judge_report.md`
- 与 v3 对比报告：`eval/results/run_20260912_213128_judged_vs_v3.md`
