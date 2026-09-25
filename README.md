# 校园 AI 咨询助手

基于 Spring Boot、FastAPI、LangChain 和 Chroma 的校园制度 RAG 咨询系统，面向学生手册、学籍管理、考试重修、奖助评优、宿舍管理等领域。

## Architecture

```text
Vue 前端
   |
Spring Boot 业务网关
   |  鉴权、会话历史、内部 HMAC、SSE 转发
FastAPI RAG 服务
   |  结构化摄取、混合召回、Rerank、Evidence Object
Chroma + SQLite/MySQL
```

## Modules

### `ai-springboot`

- 用户 Token 鉴权和管理员权限校验
- 游客签名 Cookie 会话
- 登录用户会话与消息历史
- Spring Boot 到 FastAPI 的内部 HMAC 认证
- `/api/chat/stream` SSE 流式转发
- 文档上传、版本、重索引和删除接口

### `ai-rag`

- PDF、DOCX、XLSX、CSV、JSON、HTML、Markdown、TXT 结构化摄取
- 章节、表格和记录路由分块
- 文件级、分块级和 Embedding 语义三层去重
- Query Normalize、Query Rewrite 和 Query Planner
- BM25 + 向量混合召回
- 多 Query RRF、Rerank、覆盖补召回和 Evidence Object
- 现行、历史、截至日期和年级适用范围治理
- thread_id 短期记忆、Checkpoint、revision 和 TTL
- 140 题随机集、年级适用性测试、RAGAS 和分层指标

### `ai-vue`

- 校园问题咨询页面
- SSE 流式回答展示
- 会话历史与游客/登录用户模式
- 管理员文档管理页面

## Quick Start

### 1. Python RAG 服务

```powershell
cd ai-rag
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python seed.py
uvicorn app.main:app --reload --port 8000
```

### 2. Spring Boot 网关

```powershell
cd ai-springboot
mvn spring-boot:run
```

默认运行在 `http://127.0.0.1:8080`。

### 3. Vue 前端

```powershell
cd ai-vue
npm install
npm run dev -- --host 127.0.0.1 --port 4173
```

前端访问地址：`http://127.0.0.1:4173/chat`。

## Configuration

仓库不提交 `.env` 和任何 API Key。参考 `ai-rag/.env.example` 配置：

```text
LLM_MODEL
LLM_BASE_URL
LLM_API_KEY
EMBEDDING_MODEL
EMBEDDING_BASE_URL
EMBEDDING_API_KEY
RERANK_MODEL
RERANK_API_KEY
RAGAS_LLM_*
```

## Evaluation

Python RAG 服务包含：

- 140 条随机问答评测集
- 20 条年级适用性评测集
- LLM-as-Judge 语义评分
- Recall@3、Hit@3、Context Recall、引用有效率和 P50/P95 延迟
- RAGAS Faithfulness、Context Precision、Context Recall 等旁路指标

评测脚本位于 `ai-rag/eval/`。

## Security

- `.env`、数据库、上传文件、日志和评测结果不会进入 Git。
- 生产环境必须替换内部 HMAC、游客会话和数据库密钥。
- 请勿将 API Key 写入源码、README 或提交历史。
