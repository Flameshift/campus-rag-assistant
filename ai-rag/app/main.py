# FastAPI 入口：注册路由、跨域配置与 Swagger 文档。

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from . import dedup, models
from .admin_service import admin_document_service
from .db import SessionLocal, init_db
from .document_loader import load_documents_from_file
from .internal_auth import InternalAuthMiddleware
from .rag_service import rag_service
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用启动时初始化数据库表。"""
    init_db()
    short_term_memory.start_background_cleanup()
    try:
        yield
    finally:
        short_term_memory.stop_background_cleanup()


app = FastAPI(title="AI 咨询助手 RAG 服务", version="0.1.0", lifespan=lifespan)
app.add_middleware(InternalAuthMiddleware)


@app.get("/")
def root():
    """服务根路径：返回入口信息，方便浏览器直接访问。"""
    return {"service": "ai-rag", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    """健康检查：同时返回当前运行模式（demo 或 rag）。"""
    return {"status": "ok", "mode": "demo" if rag_service.use_fake else "rag"}


@app.get("/api/knowledge/count")
def knowledge_count():
    """查询知识库中的分块数量。"""
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
    """上传资料接口，支持两种方式：

    - text：直接传纯文本字符串。
    - file：上传 PDF / Word / Markdown / TXT 文件。
    - upload_id：客户端幂等键，重复提交同一键只处理一次。
    """
    if text:
        filename = "text.txt"
        content = text.encode("utf-8")
    elif file is not None:
        filename = file.filename or "file.txt"
        content = await file.read()
    else:
        raise HTTPException(status_code=400, detail="请提供 text 或 file")

    if not content.strip():
        raise HTTPException(status_code=400, detail="文件内容为空")

    # 未传 upload_id 时用内容哈希兜底，保证相同内容不会重复入库。
    upload_id = upload_id or dedup.file_hash(content)

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

    if result.get("idempotent"):
        message = "相同任务已处理过，直接返回"
    elif result.get("skipped_file"):
        message = "文件已存在，跳过重复入库"
    else:
        message = f"处理完成：新增 {result['added']} 个分块，跳过 {result['skipped']} 个重复分块"

    return UploadResponse(filename=filename, chunks=result.get("added", 0), message=message)


@app.get("/api/admin/documents")
def admin_documents():
    """管理员文档列表，只返回源文档和索引摘要。"""
    return {"documents": admin_document_service.list_documents()}


@app.get("/api/admin/tasks")
def admin_tasks(document_id: int | None = None):
    """管理员任务列表。"""
    return {"tasks": admin_document_service.list_tasks(document_id)}


@app.get("/api/admin/documents/{document_id}/versions")
def admin_document_versions(document_id: int):
    versions = admin_document_service.list_versions(document_id)
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
    content = await file.read()
    if not content.strip():
        raise HTTPException(status_code=400, detail="文件内容为空")
    filename = file.filename or "document"

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

    task_id = task_queue.submit("version_upload", document_id, run)
    return {"document_id": document_id, "task_id": task_id, "status": "queued"}


@app.post("/api/admin/documents/{document_id}/disable")
def admin_disable_document(document_id: int):
    if not admin_document_service.set_status(document_id, "disabled", None):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"document_id": document_id, "status": "disabled"}


@app.post("/api/admin/documents/{document_id}/restore")
def admin_restore_document(document_id: int):
    if not admin_document_service.set_status(document_id, "done", None):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"document_id": document_id, "status": "active"}


@app.post("/api/admin/documents/{document_id}/reindex")
def admin_reindex_document(document_id: int):
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
    task_id = task_queue.submit(
        "delete",
        document_id,
        lambda _: admin_document_service.delete_document(document_id),
    )
    return {"document_id": document_id, "task_id": task_id, "status": "queued"}


@app.post("/api/admin/documents/{document_id}/activate-version")
def admin_activate_version(document_id: int):
    if not admin_document_service.activate_version(document_id, None):
        raise HTTPException(status_code=404, detail="文档版本不存在")
    return {"document_id": document_id, "status": "active"}


@app.get("/api/jobs/{upload_id}")
def job_status(upload_id: str):
    """查询上传任务状态，便于前端轮询异步处理结果。"""
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
    """问答接口：接收问题与对话历史，返回回答和参考来源。"""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    # 把 Pydantic 模型转成普通字典，交给 RAG 服务处理。
    history = [item.model_dump() for item in req.history]
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
    """SSE 流式问答接口：依次返回 token / sources / done 事件。"""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    history = [item.model_dump() for item in req.history]

    def event_stream():
        for event in rag_service.stream_chat(
            req.question,
            history,
            thread_id=req.thread_id,
            history_trusted=req.history_trusted,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.delete("/api/memory/{thread_id}")
def delete_short_term_memory(thread_id: str):
    """删除指定 thread_id 的短期记忆。"""
    deleted = short_term_memory.delete(thread_id)
    return {"thread_id": thread_id, "deleted": deleted}
