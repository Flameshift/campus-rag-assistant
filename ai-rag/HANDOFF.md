# AI 咨询助手 Python 后端交接文档

更新时间：2026-10-26 21:20

## 1. 当前状态

- 仓库：`D:\BaiduNetdiskDownload\ai助手\code`
- 分支：`main`
- 当前 HEAD：`b612ee8 fix: harden RAG streaming and document pipeline`
- 当前 Python 后端重构尚未提交
- 前端和 Spring Boot 本轮没有修改

当前工作区包含以下未提交改动：

```text
 D ai-rag/app/document_loader.py
 M ai-rag/app/admin_service.py
 M ai-rag/app/answer_verifier.py
 M ai-rag/app/evidence_objects.py
 M ai-rag/app/ingestion/llm_planner.py
 M ai-rag/app/ingestion/loaders.py
 M ai-rag/app/main.py
 M ai-rag/app/query_rewriter.py
 M ai-rag/app/rag_service.py
 M ai-rag/app/upload_service.py
 M ai-rag/tests/test_stream_cancellation.py
?? ai-rag/app/api/
?? ai-rag/app/rag/
?? ai-rag/app/streaming/
?? ai-rag/tests/test_refactor_contract.py
?? ai-rag/HANDOFF.md
```

## 2. 这次重构解决了什么

重构前的两个主要问题：

1. `app/main.py` 同时负责应用生命周期、路由、上传、管理员接口和 SSE 处理。
2. `app/rag_service.py` 同时负责模型初始化、检索、证据扩展、问答编排和记忆写入。

本次目标是只调整职责边界，不改变对外 API 和业务行为。

## 3. 当前目录结构

```text
ai-rag/app/
├── main.py
├── rag_service.py
├── document_loader.py          # 已删除
├── api/
│   ├── __init__.py
│   ├── admin_routes.py
│   ├── chat_routes.py
│   ├── system_routes.py
│   └── upload_routes.py
├── rag/
│   ├── __init__.py
│   ├── cancellation.py
│   ├── contracts.py
│   ├── observability.py
│   ├── pipeline.py
│   ├── runtime.py
│   ├── retrieval.py
│   └── evidence.py
└── streaming/
    ├── __init__.py
    └── sse_response.py
```

## 4. 各模块职责

| 模块 | 职责 |
| --- | --- |
| `app/main.py` | 只创建 FastAPI、初始化数据库、启停短期记忆清理线程、注册内部认证和 Router |
| `app/api/system_routes.py` | `/`、`/health`、`/api/knowledge/count` |
| `app/api/upload_routes.py` | `/api/upload`、`/api/jobs/{upload_id}` |
| `app/api/admin_routes.py` | 管理员文档、版本、重索引、删除和任务接口 |
| `app/api/chat_routes.py` | 普通问答、SSE 流式问答、短期记忆删除 |
| `app/streaming/sse_response.py` | 客户端断开时显式关闭异步 SSE 生成器 |
| `app/rag/cancellation.py` | `StreamCancelled` 和流式取消检查 |
| `app/rag/observability.py` | 请求级耗时 ContextVar 和计时写入 |
| `app/rag/runtime.py` | `RagRuntime`：LLM、Embedding、Chroma、BM25、知识库写入和混合检索器 |
| `app/rag/retrieval.py` | `RagRetrieval`：查询规划、召回、Rerank、证据构建和 Prompt 准备 |
| `app/rag/evidence.py` | `RagEvidence`：适用范围、版本过滤、证据覆盖、父块与相邻块扩展 |
| `app/rag/contracts.py` | `PreparedChat`：生成阶段之前的类型化检索结果 |
| `app/rag/pipeline.py` | `RagPipeline`：普通生成、SSE、置信度、记忆和耗时日志编排 |
| `app/rag_service.py` | 薄门面，组装组件并保留 `RagService`、`StreamCancelled`、`rag_service` |

当前对象组合关系：

```text
RagService
  -> RagRuntime
  -> RagEvidence(runtime)
  -> RagRetrieval(runtime, evidence)
  -> RagPipeline(runtime, retrieval)
```

`RagService` 不再通过 Mixin 继承共享隐式状态，也不再承载问答编排。知识库写入、
向量去重和删除通过 `RagRuntime` 的明确方法完成；`RagRetrieval` 只通过构造函数
注入的 `runtime` 和 `evidence` 协作；`RagPipeline` 统一负责普通与流式问答。

`RagRetrieval.prepare_chat()` 已拆分为查询准备、范围解析、候选召回、Rerank、
证据构建和 Prompt 构建六个阶段，并返回类型化 `PreparedChat`。

`RagService` 的公开入口没有改变：

- `RagService.chat()`
- `RagService.stream_chat()`
- `RagService.knowledge_count()`
- `rag_service` 模块级单例
- `StreamCancelled` 仍可从 `app.rag_service` 导入

## 5. 当前流式取消链路

```text
浏览器 AbortController
  -> Spring Boot 与浏览器连接关闭
  -> Spring Boot 写 SSE 失败并关闭 Python 响应流
  -> FastAPI CancellableStreamingResponse 感知响应结束
  -> 设置 cancel_event
  -> 关闭同步 RAG 生成器
  -> rag_service.stream_chat() 在阶段边界停止
  -> 不再继续拉取 LLM token、复核答案或写短期记忆
```

取消检查点包括：

- 短期记忆读取后
- Query Rewrite 后
- Query Plan 后
- 检索前后
- Rerank 前后
- 证据构建前
- Prompt 构建前
- 每次请求下一个 LLM token 前
- 答案复核前
- 置信度计算前
- 写入短期记忆前

已知边界：

- 如果线程正阻塞在检索、Rerank 或模型 SDK 的 `next()` 内，取消只能在当前阻塞调用返回后生效。
- 当前依赖连接关闭传播取消，没有单独的取消 HTTP 接口。

## 6. 已移除的兼容层

`app/document_loader.py` 已删除。

原调用位置已改为直接使用：

```python
from .ingestion.service import ingestion_service

chunks = ingestion_service.load_and_split(filename, content)
```

仓库内已确认没有剩余的 `document_loader` 或 `load_documents_from_file` 引用。

如果仓库外有脚本直接导入 `app.document_loader`，需要同步改为
`app.ingestion.service.ingestion_service`。

## 7. 验证结果

当前拆分后的 Python 代码已验证：

```text
Python unittest：93 项全部通过
Pyright：0 errors / 0 warnings
OpenAPI 业务路径：16
知识库分块数：714
RagService MRO：RagService -> object
组件：RagRuntime / RagEvidence / RagRetrieval / RagPipeline
```

已验证导入：

```python
from app.main import app
from app.rag_service import RagService, StreamCancelled, rag_service
```

前端和 Spring 验证：

- 已完成 `npm run build`，Vue 生产构建通过
- 已完成 `mvn -q -DskipTests compile`，Spring Boot 编译通过
- Spring 经内部签名调用 Python `/api/knowledge/count`，返回 `{"count":714}`
- 已完成真实 `/api/chat` 冒烟测试：
  - `mode=rag`
  - 返回 8 条来源
  - 置信度 `0.7069`
  - 总耗时约 `86.8s`
  - 回答正确给出标准学制四年、最长六年，并附来源

新增的 `tests/test_refactor_contract.py` 锁定显式组件组合、公开导出、委托关系、
Prompt 构建依赖，以及 16 条 OpenAPI 路径对应的 HTTP 方法。

## 8. 当前运行状态

最近一次端口检查：

```text
127.0.0.1:8000  Python/FastAPI（新代码）
127.0.0.1:8080  Spring Boot
127.0.0.1:4173  Vue/Vite
```

`8000` 已按交接要求重启，新进程加载了拆分后的模块结构。
当前进程号只是快照，可能会变化：

```text
8000: 12228
8080: 8320
4173: 26068
```

启动命令：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

本次后台进程日志：

```text
%TEMP%\ai-rag-uvicorn.stdout.log
%TEMP%\ai-rag-uvicorn.stderr.log
```

启动后检查结果：

```text
GET /health -> {"status":"ok","mode":"rag"}
GET /openapi.json -> 16 条路径
GET http://127.0.0.1:8080/api/knowledge/count -> {"count":714}
GET http://127.0.0.1:4173 -> HTTP 200
```

## 9. 交接后的推荐步骤

### 9.1 运行 Python 测试

```powershell
cd "D:\BaiduNetdiskDownload\ai助手\code\ai-rag"
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

### 9.2 检查导入、路由和知识库

```powershell
cd "D:\BaiduNetdiskDownload\ai助手\code\ai-rag"
.\.venv\Scripts\python.exe -c "from app.main import app; from app.rag_service import RagService, StreamCancelled, rag_service; print(len(app.openapi()['paths'])); print([c.__name__ for c in RagService.__mro__]); print(type(rag_service.runtime).__name__, type(rag_service.evidence).__name__, type(rag_service.retrieval).__name__, type(rag_service.pipeline).__name__); print(rag_service.knowledge_count())"
```

预期：

```text
16
RagRuntime RagEvidence RagRetrieval RagPipeline
714
```

静态检查：

```powershell
npx --yes pyright --pythonpath .\.venv\Scripts\python.exe app tests/test_refactor_contract.py tests/test_stream_cancellation.py
```

预期输出：`0 errors, 0 warnings, 0 informations`。

### 9.3 检查前端和 Spring Boot

```powershell
cd "D:\BaiduNetdiskDownload\ai助手\code\ai-vue"
npm run build
```

```powershell
cd "D:\BaiduNetdiskDownload\ai助手\code\ai-springboot"
$env:JAVA_HOME='C:\Program Files\Java\latest\jdk-17'
mvn -q -DskipTests compile
```

### 9.4 重启 Python 服务

先确认 `8000` 的监听进程：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

停止旧进程后，在 `ai-rag` 目录启动：

```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
```

如果使用后台进程，需要继续重定向 stdout/stderr 并检查日志。

### 9.5 启动后检查

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8080/api/knowledge/count
Invoke-WebRequest http://127.0.0.1:4173 -UseBasicParsing
```

预期：

- Python `/health` 返回 `status=ok`
- Spring 知识库计数返回 `count=714`
- Vue 页面返回 HTTP 200

## 10. 提交前检查

```powershell
cd "D:\BaiduNetdiskDownload\ai助手\code"
git status --short
git diff --check
git diff --stat
git diff
```

注意：普通 `git diff --stat` 不包含新增文件。
需要同时检查：

```powershell
git status --short
git diff --stat --cached
git ls-files --others --exclude-standard
```

确认后再暂存和提交：

```powershell
git add -A
git commit -m "refactor: split FastAPI routes and RAG pipeline"
```

## 11. 主要风险

1. `8000` 已重启；后续修改 Python 模块后仍需重启服务，或显式使用 `--reload`。
2. `RagService` 通过组合对象协作；修改 `RagRuntime`、`RagEvidence` 或
   `RagRetrieval` 的公开方法时，需要同步检查门面委托和契约测试。
3. 流式取消是协作式取消，不能强行中断正在阻塞的外部 SDK 调用。
4. `document_loader.py` 已删除，仓库外旧导入会失效。
5. 本轮只做结构拆分，没有改变 RAG 算法、检索参数或模型配置。

## 12. 回滚参考

当前重构尚未提交，回滚应以本次工作区改动为单位，不要影响已提交的
`b612ee8` 流式稳定性改动。

建议先保留一份差异：

```powershell
git diff > refactor-before-review.diff
git status --short >> refactor-before-review.diff
```
