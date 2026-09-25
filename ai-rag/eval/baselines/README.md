# 基线管理说明

每次修改检索、分块、模型或 Prompt 后，把结果与对应评估集的当前基线对比，避免“感觉变好了”。

## 当前基线

### 常规集 v7

- `v7_student_handbook_parent_child_baseline.json`：机器可读基线
- `v7_student_handbook_parent_child_baseline.md`：人工可读基线

基线 v7 关键指标（结构化分块 + 父子检索 + 回答复核 + 系统治理）：

```text
77 题，完全正确 77（100.0%），部分正确 0，错误 0，无答案拒答 5/5
Chroma cosine 距离，714 个 canonical 分块，714 个分块带父级元数据
BM25 + 向量粗筛 20 条，Rerank Top-5，父子扩展和相邻扩展兜底
回答完整性复核开启，Spring Boot -> Python 内部 HMAC 开启
77/77 答案包含行内证据编号和末尾来源列表
```

### 挑战集 v2

- `v2_student_handbook_challenging_baseline.json`：机器可读基线
- `v2_student_handbook_challenging_baseline.md`：人工可读基线

挑战集 v2 关键指标（口语化、指代、错误前提、混合意图、提示注入等）：

```text
40 题，完全正确 40（100.0%），部分正确 0，错误 0，无答案拒答 6/6
40/40 答案包含行内证据编号和末尾来源列表
```

### 随机复核集 v1

- `v1_student_handbook_random_reviewed_baseline.json`：机器可读基线
- `v1_student_handbook_random_reviewed_baseline.md`：人工可读基线

随机复核集 v1 关键指标（140 道随机候选，复核并验证后全量运行）：

```text
140 题，完全正确 134（95.7%），部分正确 4，错误 2，无答案拒答 15/15
接口错误 0，Judge 请求错误 0，真值分块召回率 95.6%
平均来源 8.89 条，P50 延迟 88.13 秒，P95 延迟 102.01 秒
已记录 2 道题目自包含性不足，不直接与常规集 v7 的 100.0% 横向比较
```

### 随机复核集 v2

- `v2_student_handbook_random_evidence_object_baseline.json`：机器可读基线
- `v2_student_handbook_random_evidence_object_baseline.md`：人工可读基线

随机复核集 v2 修订了两道不可自包含题，并开启 Evidence Object：

```text
140 题，完全正确 134（95.7%），部分正确 5，错误 1，无答案拒答 15/15
Recall@3 91.6%，Hit@3 96.8%，完整上下文召回 97.2%
平均来源 8.24 条，平均最终上下文约 1748 Token
```

历史基线：

```text
v1：纯向量语义检索，93.5%
v2：BM25 + 向量混合检索，96.1%
v3：BM25 混合检索 + 语义去重，96.1%
v4：BM25 混合检索 + 语义去重 + Rerank，96.1%
v5：结构化分块 + Rerank + 相邻分块扩展，97.4%
v6：回答范围约束 + 证据引用 + 自动来源列表，100.0%
v7：父子检索 + 回答复核 + 系统治理，常规集 100.0%，挑战集 100.0%
```

## 新实验结果对比

1. 先跑新一轮评估：

```powershell
.\.venv\Scripts\python.exe eval\eval_runner.py
.\.venv\Scripts\python.exe eval\judge_results.py eval\results\<new_run>.jsonl --model deepseek-chat
```

2. 与对应基线对比：

```powershell
.\.venv\Scripts\python.exe eval\compare_baseline.py --judged eval\results\<new_run>_judged.jsonl
.\.venv\Scripts\python.exe eval\compare_baseline.py --baseline eval\baselines\v2_student_handbook_challenging_baseline.json --judged eval\results\<challenge_run>_judged.jsonl
```

3. 默认与常规集 v7 对比，结果输出到：

```text
eval/results/<new_run>_judged_vs_v7.md
```

## 记录规范

- 知识库版本变化（新增文档、重新分块）必须记录
- 评估集一旦修改，需要升级版本号并重跑全部基线
- 对比时至少记录：完全正确率、部分正确数、错误数、平均延迟、分题型得分
