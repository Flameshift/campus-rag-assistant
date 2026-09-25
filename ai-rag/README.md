# AI 咨询助手 RAG 后端（ai-rag）

基于 FastAPI + LangChain + Chroma 的简单 RAG 问答框架，配合 `ai-vue` 前端使用。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python seed.py
uvicorn app.main:app --reload --port 8000
```

未配置 API Key 时自动进入演示模式（本地模拟回答），配置 `.env` 中的 `LLM_*` 与 `EMBEDDING_*` 后切换为真实 RAG。

## 接口

- `GET /health`：健康检查
- `GET /api/knowledge/count`：知识库分块数量
- `POST /api/upload`：上传资料（`text` 参数或 `file` 文件）
- `POST /api/chat`：问答，请求体 `{ "question": "...", "history": [], "thread_id": "..." }`
- `DELETE /api/memory/{thread_id}`：删除指定线程的短期记忆
- `GET /docs`：Swagger 文档

## 目录结构

```text
app/
  main.py             FastAPI 入口
  config.py           环境变量配置
  schemas.py          请求/响应模型
  document_loader.py  兼容入口，内部调用结构化摄取流程
  ingestion/          统一文档块、格式 Loader、结构路由和多种 Splitter
  parenting.py        父级分组与父上下文窗口选择
  answer_verifier.py  回答完整性复核与一次补全
  answer_validator.py 数字对象一致性与子问题覆盖校验
  query_planner.py    时间语义、子问题拆分和指代风险
  evidence_selector.py 精确文件标题证据加权
  short_term_memory.py 基于 thread_id 的短期状态与 Checkpointer
  rag_service.py      RAG 核心流程
  db.py               数据库连接与初始化
  models.py           source_file / chunk / upload_job 模型
  dedup.py            文件哈希与分块哈希工具
  upload_service.py   上传处理编排（幂等 + 三层去重）
data/
  knowledge.md        样例知识库
seed.py               初始化样例知识库
```

## 防重复上传框架

- 上传接口支持 `upload_id` 幂等键，重复提交只处理一次。
- 文件级 `SHA-256` 去重：同一文件内容只入库一次。
- 分块级归一化哈希去重：不同文件中的相同片段只存一份。
- 任务状态可通过 `GET /api/jobs/{upload_id}` 查询。

后续可自行完善：异步队列处理、分布式锁、MinHash 近似去重、向量库失败补偿与定期清理。

## 结构化摄取

上传文件先被解析成统一的 `DocumentBlock`，再根据块类型选择：

- 章节分块：PDF、DOCX、Markdown、HTML 和普通文本
- 表格分块：DOCX 表格、XLSX，每一组保留表头
- 记录分块：CSV、JSON，每个数据记录保留字段名
- 递归分块：无法识别结构时的最终兜底

当规则结构置信度低于阈值时，系统可以让 LLM 返回章节边界和分块策略，
但不会让模型重写知识库正文。新分块携带 `section_path`、`parent_key`、
`parent_id`、`parent_type`、`order_index` 和版本信息。

## 父子检索

检索始终以子块为基本单位，子块负责 BM25、向量召回和 Rerank。命中后再按
`parent_id` 恢复完整条款、表格或记录组；旧数据没有 `parent_id` 时回退到
`parent_key`。父级扩展成功且补齐了同组证据时，不再对该命中块执行相邻扩展；
只有父级不可用或扩展为空时，才使用相邻分块兜底。

父级分组优先遵循文档结构：

- PDF、DOCX、Markdown、HTML 和普通文本按标题、章节或条款分组
- DOCX、XLSX 表格按表格或工作表分组
- CSV、JSON 按数据集和记录类型分组
- 无法识别结构时按固定字符数和子块数窗口分组

父上下文有独立字符数、子块数和新增分块上限，避免把整章或整张表塞入 Prompt。

## 查询规划与证据校验

检索前依次执行确定性 Query Normalizer、Query Rewrite 和轻量 Query Planner：

- Query Normalizer 统一全角字符、口语填充词、领域别名和中文数字表达，例如
  “挂科”转为“考核不合格”，“十学时”补充为“十学时（10学时）”。
- 有历史时，Query Rewrite 负责把“这个怎么处理”等追问改写成自包含查询。
- 无历史时，口语化问题可以通过规则归一；超过阈值的长描述可以调用 LLM 压缩，
  但数字、文件标题和否定条件会被校验，丢失关键约束时回退原查询。
- Query Planner 识别 `current`、`historical`、`as_of` 和 `compare` 四类时间语义，
  对“另外”“同时”“以及”等混合意图拆分为最多 3 个子问题。
- 对没有历史上下文的“本办法”“第一条”，以及“这个怎么处理”等缺少对象的表达，
  系统返回一次澄清问题，不直接进行低置信检索。

当问题包含多个子问题时，每个子查询并行执行 BM25 + 向量混合检索，再使用加权
RRF 合并排名。合并后的候选统一进入 Rerank。若合并后仍有子问题没有进入上下文，
系统使用 BM25 进行低成本补召回，不额外调用 Embedding。回答阶段会建立子问题
覆盖矩阵，并将覆盖不足作为置信度风险信号。

当前未引入 HyDE 或 answer-first retrieval，这两类生成式检索需要单独评测其对
事实型、数字型和条款型问题的影响后再启用。

多 Query 的查询向量默认一次性批量计算，再分别执行向量检索和 BM25；如果批量
Embedding 不可用，会自动回退到逐 Query 并行调用。

文档向量化默认按 `EMBEDDING_BATCH_SIZE` 分批，并使用有界线程池同时处理多个
批次，批次结果保持原始顺序。并发数由 `EMBEDDING_MAX_CONCURRENCY` 控制。

数字校验会保留数字对应的对象、单位、上下文和带编号分项，检测“对象相同但数值
冲突”的情况。高置信冲突默认只触发复核和置信度降级，不自动改写原文。问题明确
引用 `《文件名称》` 时，正文精确命中该标题的证据会获得 Rerank 加权。

## Evidence Object

同一文件、同一版本、同一父级且 `order_index` 连续的检索子块，会合并成一个
Evidence Object。合并后保留条款顺序和全部原始 `source_chunk_ids`，Prompt 中
按对象展示，评测和引用仍可追溯到原始分块。

当前完整随机集实验表明，Evidence Object 开启后可将平均来源数从 9.47 降到
8.24，同时保持并略微提升 Recall@3 和答案正确率。未验证有效的条件扩展、
Claim Coverage 和 Minimal Evidence Set 已从运行链路移除。

## 短期记忆

问答请求可以携带可选的 `thread_id`。启用后，服务会保存每个线程最近的消息状态，
并在下一次请求时恢复。当前状态包含：

- `messages`：最近对话消息
- `rolling_summary`：为后续摘要压缩预留
- `entities`、`current_task`、`pending_question`：为后续任务状态预留
- `version`、`updated_at`：状态版本和 TTL 管理

状态通过 `ShortTermMemory` 接口保存，当前默认使用数据库 Checkpointer。该接口与
LangGraph 的 State/Checkpointer 语义兼容，后续可以替换为 LangGraph 的
`SqliteSaver`、`PostgresSaver` 或 Redis Checkpointer。未传 `thread_id` 时保持无状态行为。

## 文档版本与管理员接口

源文件记录包含 `document_id`、`version`、`version_status`、`is_current`、
`document_number`、`document_title`、`document_type`、`issuing_department`、
`effective_date`、`expiry_date`、`supersedes`、`applicability` 和
`document_aliases`。普通问题默认只使用现行版本；明确询问历史版本或
“截至某日期”时，版本过滤器会放开，并对带生效日期的文档执行按时间选择。

管理员接口支持：

```text
GET    /api/admin/documents
GET    /api/admin/documents/{id}/versions
POST   /api/admin/documents/{id}/versions
POST   /api/admin/documents/{id}/activate-version
POST   /api/admin/documents/{id}/reindex
POST   /api/admin/documents/{id}/disable
POST   /api/admin/documents/{id}/restore
DELETE /api/admin/documents/{id}
GET    /api/admin/tasks
```

版本上传、重新索引和删除使用数据库任务记录和后台线程池执行，任务状态可通过
管理员任务接口查询。

## 适用年级与往届回退

源文件通过 `applicability` 记录适用对象，例如 `2024级本科生`。问答时会先从用户
问题中识别 `2024级`、`26级`、`二六级` 等年级表达，再执行以下策略：

- 用户年级与文件适用对象精确匹配时，直接使用匹配文件。
- 用户年级没有精确文件时，优先使用通用文件。
- 没有精确文件或通用文件时，使用最近的现行文件作为往届参考，并在回答前明确
  提示版本不匹配。
- 用户没有说明年级时，使用最新现行文件，并标注该文件的适用对象。
- 没有任何候选文件时，不生成低置信答案，而是提示知识库缺少适用文件。

登录用户的 `thread_id` 由 Spring Boot 根据 Token 和 `conversation_id` 生成；
游客使用 HMAC 签名 Cookie。Python 通过内部时间戳签名校验所有 `/api/*` 请求，
客户端不能直接伪造 `thread_id` 调用 Python 服务。

登录用户的 `conversation/message` 数据库是用户可见历史的权威来源。Spring Boot
在回答成功后事务性写入 user 和 assistant 消息，Python Checkpoint 只作为可重建的
短期运行态。游客暂不写入 Spring 会话库，由签名 Cookie 和 Python TTL Checkpoint
共同管理短期会话。

短期状态使用 `revision` 做乐观并发控制，并有后台 TTL 清理线程。若历史短期状态
需要补齐父级元数据，可停止 Python 服务后执行：

```powershell
.\.venv\Scripts\python.exe backfill_parent_metadata.py
```

## 回答约束与阶段耗时

回答 Prompt 会限制模型只回答用户直接询问的范围，不汇总后果相似的其他条款，
不把可选条件写成强制条件，也不补充资料中不存在的日期、金额或流程。

普通问答接口会返回 `timings` 和 `request_id`，流式接口会发送 `timings` 事件。
当前记录阶段包括：

```text
query_rewrite_ms
query_embedding_ms
query_embedding_batch_ms
query_embedding_batch_used
retrieval_scope_ms
retrieval_source_scope_count
retrieval_ms
retrieval_query_count
clarification_ms
evidence_coverage_fill_ms
rerank_ms
parent_expansion_ms
neighbor_expansion_ms
prompt_build_ms
subquestion_count / subquestion_covered_count
answer_verification_ms
llm_first_token_ms      流式请求
llm_generation_ms
total_ms
```

服务日志会输出相同字段，便于按请求 ID 排查延迟和统计 P50/P95。

## RAGAS 旁路评测

RAGAS 使用独立 `.venv-ragas`，不会修改在线问答环境的 LangChain 版本：

```powershell
python -m venv .venv-ragas
.\.venv-ragas\Scripts\python.exe -m pip install -r requirements-ragas.txt
.\.venv-ragas\Scripts\python.exe eval\ragas_eval.py `
  --judged .\eval\results\<run>_judged.jsonl `
  --limit 20 --workers 2
```

脚本从 SQLite 的 chunk 表恢复 `reference_contexts`，计算 Faithfulness、Answer
Relevancy、Context Precision、Context Recall、Answer Correctness 和
Noise Sensitivity。结果输出 CSV、JSON 和 Markdown 报告。全量评测建议离线运行。

RAGAS Judge 与在线回答模型使用独立配置，避免评测模型影响线上链路：

```text
RAGAS_LLM_MODEL
RAGAS_LLM_BASE_URL
RAGAS_LLM_API_KEY
```

## 年级适用性评测

使用 `cohort_applicability_v1` 验证精确匹配、往届回退和未说明年级时的版本提示：

```powershell
.\.venv\Scripts\python.exe eval\cohort_applicability_eval.py `
  --input .\eval\generated\cohort_applicability_v1\cohort_applicability_v1.jsonl `
  --workers 2
```
