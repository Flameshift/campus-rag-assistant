"""FastAPI 应用入口。

main.py 只负责 HTTP 层编排，不承载具体 RAG、上传或文档管理算法：
- 注册应用生命周期、内部 HMAC 认证中间件和全部 HTTP 路由；
- 校验请求参数并调用 rag_service、UploadService、admin_document_service；
- 把同步结果转成 JSON，把流式结果转成 SSE；
- 把耗时操作提交给 task_queue，把短期记忆操作委托给 short_term_memory。

主要路由分组：
- 基础探测：/、/health
- 知识库与上传：/api/knowledge/count、/api/upload、/api/jobs/{upload_id}
- 管理员文档治理：/api/admin/**
- 问答：/api/chat、/api/chat/stream
- 会话记忆：/api/memory/{thread_id}
"""

import json
import logging
import threading
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool

from . import dedup, models
from .admin_service import admin_document_service
from .db import SessionLocal, init_db
from .document_loader import load_documents_from_file
from .internal_auth import InternalAuthMiddleware
from .rag_service import StreamCancelled, rag_service
from .short_term_memory import short_term_memory
from .task_queue import task_queue
from .schemas import (
    ChatRequest,
    ChatResponse,
    Source,
    UploadResponse,
)
from .upload_service import UploadService

# 让应用自身的 INFO 日志（语义去重决策等）输出到控制台。
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


class CancellableStreamingResponse(StreamingResponse):
    """确保客户端断开时关闭异步 SSE 生成器和其后的同步 RAG 生成器。"""

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # 断开响应时普通 return 不一定会立刻回收 async generator，
            # 这里显式 aclose，确保 event_stream 的 finally 能执行。
            with anyio.CancelScope(shield=True):
                close = getattr(self.body_iterator, "aclose", None)
                if callable(close):
                    try:
                        await close()
                    except Exception as exc:
                        logger.warning("关闭流式生成器失败: %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """管理 FastAPI 应用的启动和关闭资源。

    启动阶段必须先把数据库表和短期记忆清理线程准备好，之后才允许应用开始接收请求。
    yield 之前的代码只在进程启动时执行，yield 之后的 finally 只在进程退出时执行。
    """
    # 创建缺失的数据库表，供上传任务、文档版本和会话记忆等功能使用。
    init_db()

    # 启动短期记忆的过期清理后台线程。
    short_term_memory.start_background_cleanup()
    try:
        # 交出控制权，FastAPI 开始处理 HTTP 请求。
        yield
    finally:
        # 应用退出时停止后台清理线程，避免线程或数据库连接泄漏。
        short_term_memory.stop_background_cleanup()


# 创建 FastAPI 实例，并把 lifespan 绑定到应用启动和关闭流程。
app = FastAPI(title="AI 咨询助手 RAG 服务", version="0.1.0", lifespan=lifespan)

# 所有进入 Python 服务的 /api/ 请求都必须经过内部 HMAC 认证。
# Spring Boot 网关会生成签名，浏览器和其他外部调用方不能直接访问这些接口。
app.add_middleware(InternalAuthMiddleware)


@app.get("/")
def root():
    """返回服务标识和常用入口地址，便于人工检查服务是否可访问。"""
    return {"service": "ai-rag", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    """健康检查接口。

    mode=rag 表示已配置真实模型并执行完整 RAG 流程；
    mode=demo 表示使用假回答流程，通常用于没有模型 Key 的本地联调。
    """
    return {"status": "ok", "mode": "demo" if rag_service.use_fake else "rag"}


@app.get("/api/knowledge/count")
def knowledge_count():
    """查询向量知识库中的分块总数，主要给管理端和健康检查使用。"""
    return {"count": rag_service.knowledge_count()}


@app.post("/api/upload", response_model=UploadResponse)
async def upload(
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    upload_id: str | None = Form(None),
    uploaded_by_user_id: int | None = Form(None),
    uploader_name: str | None = Form(None),
    document_title: str | None = Form(None),
    document_number: str | None = Form(None),
    document_type: str | None = Form(None),
    issuing_department: str | None = Form(None),
    effective_date: str | None = Form(None),
    expiry_date: str | None = Form(None),
    supersedes: str | None = Form(None),
    applicability: str | None = Form(None),
    document_aliases: str | None = Form(None),
):
    """上传并索引一份新资料。

    请求必须从以下两种形式中选择一种提供内容：
    - text：直接提交纯文本；
    - file：提交 PDF、Word、Markdown 或 TXT 文件。

    其他表单字段用于保存文档标题、文号、类型、发布部门、生效日期、适用对象和别名等
    结构化元数据。upload_id 是幂等键，相同值重复提交时不会重复写入知识库。

    处理流程：
    1. 统一读取为 filename + bytes；
    2. 校验内容不能为空；
    3. 调用 UploadService 完成文件去重、解析、分块、向量化和数据库入库；
    4. 根据服务返回结果生成对前端友好的处理说明。
    """
    # 文本和文件二选一。文本先转成 UTF-8 字节，后续与文件上传共用同一条处理链路。
    if text:
        filename = "text.txt"
        content = text.encode("utf-8")
    elif file is not None:
        filename = file.filename or "file.txt"
        content = await file.read()
    else:
        raise HTTPException(status_code=400, detail="请提供 text 或 file")

    # 避免空白文本、空文件或只包含空白字符的文件进入解析和向量化流程。
    if not content.strip():
        raise HTTPException(status_code=400, detail="文件内容为空")

    # 未传 upload_id 时使用文件内容哈希兜底。
    # 这能保证相同内容在没有显式幂等键时也不会重复创建上传任务。
    upload_id = upload_id or dedup.file_hash(content)

    # 每次请求使用独立数据库会话，UploadService 负责事务边界和错误处理。
    with SessionLocal() as db:
        result = UploadService(db).process_upload(
            upload_id=upload_id,
            filename=filename,
            content=content,
            uploaded_by_user_id=uploaded_by_user_id,
            uploader_name=uploader_name,
            document_metadata={
                "document_title": document_title,
                "document_number": document_number,
                "document_type": document_type,
                "issuing_department": issuing_department,
                "effective_date": effective_date,
                "expiry_date": expiry_date,
                "supersedes": supersedes,
                "applicability": applicability,
                "document_aliases": document_aliases,
            },
        )

    # 把内部处理结果转换成前端可直接展示的摘要。
    if result.get("idempotent"):
        message = "相同任务已处理过，直接返回"
    elif result.get("skipped_file"):
        message = "文件已存在，跳过重复入库"
    else:
        message = f"处理完成：新增 {result['added']} 个分块，跳过 {result['skipped']} 个重复分块"

    return UploadResponse(filename=filename, chunks=result.get("added", 0), message=message)


@app.get("/api/admin/documents")
def admin_documents():
    """返回管理员可治理的源文档列表和索引摘要。

    这里返回的是文档级视图，不直接暴露向量库中的全部分块内容。
    """
    return {"documents": admin_document_service.list_documents()}


@app.get("/api/admin/tasks")
def admin_tasks(document_id: int | None = None):
    """返回上传、重索引、删除等后台任务记录。

    document_id 为空时返回全部任务；传入时只返回该文档关联的任务。
    """
    return {"tasks": admin_document_service.list_tasks(document_id)}


@app.get("/api/admin/documents/{document_id}/versions")
def admin_document_versions(document_id: int):
    """查询指定文档的全部版本及其当前激活状态。"""
    versions = admin_document_service.list_versions(document_id)

    # None 表示文档主记录不存在；空列表则表示文档存在但还没有版本记录。
    if versions is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"versions": versions}


@app.post("/api/admin/documents/{document_id}/versions")
async def admin_upload_document_version(
    document_id: int,
    file: UploadFile = File(...),
    uploaded_by_user_id: int | None = Form(None),
    uploader_name: str | None = Form(None),
    document_title: str | None = Form(None),
    document_number: str | None = Form(None),
    document_type: str | None = Form(None),
    issuing_department: str | None = Form(None),
    effective_date: str | None = Form(None),
    expiry_date: str | None = Form(None),
    supersedes: str | None = Form(None),
    applicability: str | None = Form(None),
    document_aliases: str | None = Form(None),
):
    """上传指定文档的新版本，并创建后台处理任务。

    新版本会沿用 document_id 的版本链，而不是创建一份互不关联的新文档。
    文件读取必须在请求线程完成，因为 UploadFile 只能在当前请求上下文中读取；
    耗时的解析、分块和向量化则交给 task_queue 在后台线程执行。
    """
    # 先把上传文件完整读入内存，后续后台线程不能再依赖 UploadFile 对象。
    content = await file.read()
    if not content.strip():
        raise HTTPException(status_code=400, detail="文件内容为空")
    filename = file.filename or "document"

    # task_queue 会把 task_id 传给 runner。
    # runner 在后台线程中执行，因此必须重新创建 SessionLocal，不能复用请求线程的会话。
    def run(task_id: str):
        with SessionLocal() as db:
            return UploadService(db).process_upload(
                upload_id=task_id,
                filename=filename,
                content=content,
                uploaded_by_user_id=uploaded_by_user_id,
                uploader_name=uploader_name,
                replace_source_file_id=document_id,
                document_metadata={
                    "document_title": document_title,
                    "document_number": document_number,
                    "document_type": document_type,
                    "issuing_department": issuing_department,
                    "effective_date": effective_date,
                    "expiry_date": expiry_date,
                    "supersedes": supersedes,
                    "applicability": applicability,
                    "document_aliases": document_aliases,
                },
            )

    # submit() 立即持久化 queued 任务并返回 task_id，接口本身不等待索引完成。
    task_id = task_queue.submit("version_upload", document_id, run)
    return {"document_id": document_id, "task_id": task_id, "status": "queued"}


@app.post("/api/admin/documents/{document_id}/disable")
def admin_disable_document(document_id: int):
    """停用指定文档，使其不再参与默认检索。"""
    # set_status 返回 False 表示文档主记录不存在，而不是状态更新失败。
    if not admin_document_service.set_status(document_id, "disabled", None):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"document_id": document_id, "status": "disabled"}


@app.post("/api/admin/documents/{document_id}/restore")
def admin_restore_document(document_id: int):
    """恢复被停用的文档，使文档主状态重新变为可用。"""
    if not admin_document_service.set_status(document_id, "done", None):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"document_id": document_id, "status": "active"}


@app.post("/api/admin/documents/{document_id}/reindex")
def admin_reindex_document(document_id: int):
    """创建文档重新索引任务。

    重索引会重新读取原始文件并执行解析、分块、去重和向量化，属于耗时操作，
    因此接口只返回 task_id，前端通过任务状态接口轮询进度。
    """
    # task_queue 传入 current_task_id，重索引服务会把进度和错误写回同一个任务记录。
    task_id = task_queue.submit(
        "reindex",
        document_id,
        lambda current_task_id: admin_document_service.reindex_document(
            document_id,
            None,
            current_task_id,
        ),
    )
    return {"document_id": document_id, "task_id": task_id, "status": "queued"}


@app.delete("/api/admin/documents/{document_id}")
def admin_delete_document(document_id: int):
    """创建文档删除任务。

    删除同时涉及数据库记录和向量库数据，因此交给后台任务执行，避免请求长时间阻塞。
    """
    task_id = task_queue.submit(
        "delete",
        document_id,
        lambda _: admin_document_service.delete_document(document_id),
    )
    return {"document_id": document_id, "task_id": task_id, "status": "queued"}


@app.post("/api/admin/documents/{document_id}/activate-version")
def admin_activate_version(document_id: int):
    """把指定版本切换为文档的当前激活版本。

    这里的 document_id 实际对应版本记录 ID；切换后旧版本会退出默认检索范围，
    但版本历史仍然保留，便于审计和回滚。
    """
    if not admin_document_service.activate_version(document_id, None):
        raise HTTPException(status_code=404, detail="文档版本不存在")
    return {"document_id": document_id, "status": "active"}


@app.get("/api/jobs/{upload_id}")
def job_status(upload_id: str):
    """查询上传、版本更新、重索引或删除任务的状态。

    upload_id 同时用于普通上传幂等键和 task_queue 生成的 task_id。
    返回值包含任务状态、关联源文件 ID 和失败信息，便于前端展示进度或错误原因。
    """
    with SessionLocal() as db:
        job = db.query(models.UploadJob).filter_by(upload_id=upload_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {
            "upload_id": upload_id,
            "status": job.status,
            "source_file_id": job.source_file_id,
            "error": job.error,
        }

@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """非流式问答接口。

    输入包含问题、最近对话历史、thread_id 和历史可信标记。
    返回完整回答、参考来源、运行模式、各阶段耗时、request_id 和置信度。
    前端在流式生成失败时也会调用这个接口进行降级重试。
    """
    # 拒绝空白问题，避免进入检索、改写和模型生成流程。
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    # 把 Pydantic 消息模型转成普通字典，rag_service 不依赖 HTTP/框架模型。
    history = [item.model_dump() for item in req.history]

    # 同步执行完整 RAG 流程，并等待最终回答生成完成。
    answer, sources, mode, timings, request_id, confidence = rag_service.chat(
        req.question,
        history,
        thread_id=req.thread_id,
        history_trusted=req.history_trusted,
    )
    return ChatResponse(
        answer=answer,
        sources=[Source(**source) for source in sources],
        mode=mode,
        timings=timings,
        request_id=request_id,
        confidence=confidence,
    )


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    """SSE 流式问答接口。

    返回 text/event-stream，每个 SSE data 行都是一个 JSON 事件。
    常见事件类型：
    - status：当前开始生成等状态提示；
    - token：增量回答片段；
    - replace：回答复核后整段替换此前内容；
    - sources：本次回答使用的参考来源；
    - timings：检索、生成等阶段耗时；
    - confidence：回答置信度和风险动作；
    - error：生成中途失败；
    - done：当前 SSE 流已正常结束。

    参数含义和非流式问答一致；区别是这里不等待完整答案，而是边生成边返回。
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    history = [item.model_dump() for item in req.history]

    # HTTP 连接断开时由 event_stream 的 finally 设置该事件。
    # rag_service 在检索、生成、复核和记忆写入之间检查它，及时停止无效工作。
    cancel_event = threading.Event()
    rag_stream = rag_service.stream_chat(
        req.question,
        history,
        thread_id=req.thread_id,
        history_trusted=req.history_trusted,
        cancel_event=cancel_event,
    )

    async def event_stream():
        """把同步 RAG 事件转成异步 SSE，并保证断连时关闭底层生成器。"""
        try:
            # StreamingResponse 不能直接消费同步生成器；在线程池中逐次读取，
            # 这样阻塞的检索/模型调用不会阻塞 FastAPI 事件循环。
            async for event in iterate_in_threadpool(rag_stream):
                if cancel_event.is_set():
                    return

                # SSE 协议要求每个事件以空行结束；ensure_ascii=False 保留中文原文。
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            # 只有正常完整生成后才发送 done；客户端取消时不伪造成功结束事件。
            if not cancel_event.is_set():
                yield 'data: {"type": "done"}\n\n'
        except StreamCancelled as exc:
            # 客户端断开属于预期控制流，不向上层转成 500。
            logger.info("chat_stream_cancelled stage=%s", exc.stage)
        finally:
            cancel_event.set()
            close = getattr(rag_stream, "close", None)
            if callable(close):
                try:
                    await anyio.to_thread.run_sync(close)
                except Exception as exc:
                    logger.warning("关闭 RAG 流失败: %s", exc)

    # StreamingResponse 会逐段消费 event_stream，而不是先拼完整字符串。
    # X-Accel-Buffering=no 用于禁止 Nginx 缓冲 SSE。
    return CancellableStreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.delete("/api/memory/{thread_id}")
def delete_short_term_memory(thread_id: str):
    """删除指定 thread_id 的短期会话记忆。

    thread_id 由 Spring Boot 根据登录用户或游客身份生成，防止一个用户删除其他会话。
    删除成功后返回 deleted=true；线程中本来没有记忆时返回 deleted=false。
    """
    deleted = short_term_memory.delete(thread_id)
    return {"thread_id": thread_id, "deleted": deleted}
