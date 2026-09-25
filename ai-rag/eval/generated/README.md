# 自动生成测试集说明

该目录用于保存由 `eval/generate_dataset.py` 生成的候选测试集。

## 生成流程

```text
知识库分块
-> 证据选择
-> 分型生成
-> 独立模型校验
-> 与现有测试集去重
-> 按题型分层划分
-> manifest
```

## 生成命令

```powershell
.\.venv\Scripts\python.exe eval\generate_dataset.py `
  --target 100 `
  --workers 4 `
  --seed 42
```

指定题型：

```powershell
.\.venv\Scripts\python.exe eval\generate_dataset.py `
  --types fact,table,procedure,multi_hop `
  --target 40
```

## 输出文件

- `candidate_pool_*.jsonl`：通过生成和独立校验的候选池
- `random_candidates_*.jsonl`：随机验证集候选
- `hidden_candidates_*.jsonl`：隐藏集候选
- `rejected_*.jsonl`：校验失败或重复题目
- `manifest_*.json`：本次生成参数、数量、错误和产物路径

## 重要限制

- 自动生成的数据默认 `review_status=pending`
- 自动校验通过不等于人工确认
- 不能直接覆盖 `student_handbook_questions.jsonl` 或挑战集
- 正式评测前必须进行人工抽检和来源复核
- 隐藏集候选在冻结前不能用于 Prompt 调优

## 当前 Pilot

`pilot_20260918/` 是首轮小规模验证，覆盖 13 种题型：

- 生成请求：26
- 独立校验通过：25
- 拒绝：1
- 随机候选：13
- 隐藏候选：12

拒绝原因是多轮追问询问时限，而参考答案只回答了办理对象，问题与答案不匹配。

## 300 条候选池 v2

目录：`pool_20260918_v2/`

```text
生成请求：300
独立模型校验通过：202
拒绝：98
隐藏集候选：62
随机集候选：140
```

拒绝主要原因：

- verbose 包含多个问题意图
- mixed_intent 缺少两个明确事项
- 关键事实没有出现在标准答案中
- 多轮题的时限或责任主体答案不完整
- 与现有测试集重复

## 自检结果

使用 `eval/check_generated_dataset.py` 对候选池做确定性检查，并分层抽取 20 条进行独立
LLM 复核：

```text
候选总数：202
确定性错误：0
需要复核的语义警告：71
严格通过：160
进入复核队列：42
LLM 分层抽检：20
LLM 接受：20
LLM 拒绝：0
```

确定性检查覆盖字段完整性、ID 和问题去重、资料分块存在性、父级映射、无答案拒答、
多轮格式、时限和责任主体完整性。剩余告警主要是转述题中的 `key_facts` 与标准答案
存在同义改写，需要人工确认。

自检报告位于 `reports/`，其中：

- `clean_candidates_*.jsonl`：无确定性错误的 160 条
- `review_candidates_*.jsonl`：包含语义告警的 42 条

## 随机测试集 v1

目录：`random_test_v1/`

基于 pool v2 的随机候选和严格通过集冻结：

```text
随机候选：140
严格通过并冻结：113
进入人工复核：27
数据集状态：candidate_pending_manual_review
```

- `random_test_v1.jsonl`：113 条随机测试候选
- `random_test_v1_review.jsonl`：27 条待复核样本
- `manifest.json`：来源、seed 和 SHA-256

这批数据已经可以用于回归运行，但在人工确认前不能称为正式黄金测试集。

### 复核结果

- 27 条待复核样本均通过独立 LLM 复核，没有发现事实错误
- `gen-verbose-0190` 已从 `verbose` 修正为 `mixed_intent`
- 复核后合并生成 140 条 `random_test_v1_reviewed.jsonl`
- `manifest_reviewed.json` 记录复核状态和 SHA-256

复核报告位于 `reports/random_test_v1_review/`。
