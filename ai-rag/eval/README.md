# 学生手册 RAG 评估集

基于 `学生手册20240906.pdf`（161 页）整理了两套问答评估集：

| 数据文件 | 题量 | 用途 |
| --- | ---: | --- |
| `student_handbook_questions.jsonl` | 77 | 常规事实、条款、表格和流程评估 |
| `student_handbook_challenging_questions.jsonl` | 40 | 生产环境口语、指代、错误前提、混合意图和注入挑战 |

## 常规集

共 **77 题**。

## 题目分布

| 类型 | 数量 | 说明 |
| --- | --- | --- |
| fact | 42 | 单条款事实查询 |
| multi_hop | 13 | 需要综合多条条款 |
| table | 10 | 金额、比例、时限等结构化信息 |
| comparison | 4 | 两类对象对比 |
| procedure | 3 | 流程与时限 |
| unanswerable | 5 | 手册未规定的问题，用于测幻觉 |

其中 72 题有标准答案，5 题无答案。

## 数据字段

```json
{
  "id": "sh-001",
  "question": "问题",
  "type": "fact",
  "answerable": true,
  "reference_answer": "标准答案",
  "key_facts": ["必须出现的关键事实"],
  "source": "学生手册20240906.pdf#p86",
  "source_section": "制度名称 + 条款",
  "difficulty": "easy"
}
```

- `source` 中的页码是 PDF 页码，不是手册印刷页码
- `answerable=false` 的题目，正确行为是拒答或说明手册未规定
- `key_facts` 用于自动计算关键词覆盖率，不能替代语义评分

## 使用步骤

1. 先把 `学生手册20240906.pdf` 上传到知识库，等待入库完成
2. 确认 Spring Boot（8080）和 Python（8000）都在运行
3. 执行评估：

```powershell
cd D:\BaiduNetdiskDownload\ai助手\code\ai-rag
.\.venv\Scripts\python.exe eval\eval_runner.py
.\.venv\Scripts\python.exe eval\eval_runner.py --input .\eval\student_handbook_challenging_questions.jsonl --workers 8
```

也可以限制题量或指定接口：

```powershell
.\.venv\Scripts\python.exe eval\eval_runner.py --limit 10
.\.venv\Scripts\python.exe eval\eval_runner.py --api http://127.0.0.1:8000/api/chat
```

## 输出结果

结果写入 `eval/results/run_YYYYMMDD_HHMMSS.jsonl`，每题记录：

```text
answer / source_count / mode / latency_seconds / error
fact_hits / fact_hit_rate   （有答案题目）
refused                     （无答案题目是否正确拒答）
```

脚本会输出汇总：

```text
题目总数
有答案题目平均关键事实覆盖率
无答案题目拒答率
平均延迟
接口错误数
```

## 评分说明

- 关键事实覆盖率是“答案里出现了多少个标准关键事实”，属于快速粗评
- 拒答率只能判断是否使用拒答话术，不能判断拒答是否合理
- 建议最终采用“自动指标 + 人工抽查”或 LLM-as-Judge 复核

## 自动生成候选集

可以基于现有知识库生成新的候选题目：

```powershell
.\.venv\Scripts\python.exe eval\generate_dataset.py --target 100 --workers 4
```

生成结果保存在 `eval/generated/`，包含候选池、随机集、隐藏集、拒绝记录和 manifest。
自动数据默认是待人工复核状态，不能直接覆盖正式测试集。详细说明见
`eval/generated/README.md`。

## 分层指标

对 Judge 结果计算检索、Rerank、上下文、引用、生成和性能指标：

```powershell
.\.venv\Scripts\python.exe eval\layer_metrics.py `
  eval\results\<run>_judged.jsonl `
  --output-dir eval\reports
```

报告包含上下文关键事实覆盖率、Rerank Top-1 分数、父级扩展命中率、引用覆盖率、
引用编号有效率、Claim 支持率、回答补全触发率和 P50/P95 延迟。

## 版本管理

- 评估集变更需要记录版本，例如常规集 `v1 77题`、挑战集 `v1 40题`
- 修改知识库、分块、Rerank 或 Prompt 后重新跑同一套题目，才能比较改进效果
- 两套评估集的基线位于 `eval/baselines/`，常规集默认与 v7 对比，挑战集使用 v2 挑战基线
