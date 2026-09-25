# 学生手册 RAG 基线 v3（语义去重）

- 基线日期：2026-09-12
- 上一版基线：v2（BM25 混合检索，96.1%）
- 知识库：278 个 canonical 分块，Chroma cosine 距离
- 回答模型：`deepseek-flash`
- 评判模型：`deepseek-chat`
- 检索方式：BM25 + 向量混合检索
- 去重方式：文件哈希 + 分块哈希 + 语义相似度

## 语义去重配置

```text
SEMANTIC_DEDUP_ENABLED = true
SEMANTIC_DEDUP_THRESHOLD = 0.75
SEMANTIC_DEDUP_GRAY_LOW = 0.60
SEMANTIC_DEDUP_TOP_K = 3
SEMANTIC_DEDUP_LLM_CONFIRM = true
SEMANTIC_DEDUP_JUDGE_MODEL = deepseek-chat
向量距离 = cosine
```

实测校准数据：

```text
高置信改写文本与原文余弦相似度：0.8427（直接去重）
灰区改写文本与原文余弦相似度：0.7403（LLM 复核后去重）
无关问题与原文余弦相似度：0.27 - 0.33
```

处理策略：

```text
similarity >= 0.75        直接判定重复
0.60 <= similarity < 0.75 交给 deepseek-chat 判断“候选内容是否已被已有内容覆盖”
similarity < 0.60         保留为新内容
```

语义重复分块只写入 `chunk` 表，记录 `duplicate_of_id` 与 `similarity`，
不写入向量库，因此不会污染检索结果。去重采用“包含式”判断：
已有内容覆盖候选信息才算重复，候选包含新信息时保留。

## 语义去重验证

```text
改写文本上传结果：新增 0 个分块，跳过 1 个重复分块
知识库向量数量：保持 278
灰区复核日志：similarity=0.7403，chunk_id=166，confirmed=True
重复记录：duplicate_of=166，vector_id=空
清理后状态：278 canonical chunks，0 duplicate records，278 vectors
```

## 评估指标

| 指标 | 数值 | 相比 v2 |
| --- | --- | --- |
| 题目总数 | 77 | - |
| 完全正确 | 74（96.1%） | 持平 |
| 部分正确 | 3 | 持平 |
| 错误 | 0 | 持平 |
| 无答案正确拒答 | 5 / 5 | 持平 |
| 平均延迟 | 11.93 秒 | +8.24 秒（外部接口波动） |

本轮部分请求出现 40-50 秒响应，延迟升高来自外部模型接口波动，
不是语义去重导致；准确率与 v2 完全一致，说明去重没有破坏检索质量。

## 剩余三道部分正确题目

| 题号 | 类型 | 原因 |
| --- | --- | --- |
| sh-009 | fact | 附加了标准答案未提及的处分细节 |
| sh-028 | procedure | 遗漏“5日内答复是否受理”，复查时限表述不准 |
| sh-060 | multi_hop | 遗漏必修课前10%、综合考评前10%等条件 |

## 数据文件

- 原始结果：`eval/results/run_20260912_201020.jsonl`
- 语义评分结果：`eval/results/run_20260912_201020_judged.jsonl`
- 语义评判报告：`eval/results/run_20260912_201020_judge_report.md`
- 与 v2 对比报告：`eval/results/run_20260912_201020_judged_vs_v2.md`
