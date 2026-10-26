"""管理员文档治理和后台任务接口。"""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..admin_service import admin_document_service
from ..db import SessionLocal
from ..task_queue import task_queue
from ..upload_service import UploadService

router = APIRouter()


@router.get("/api/admin/documents")
def admin_documents():
    """返回管理员可治理的源文档列表和索引摘要。"""
    return {"documents": admin_document_service.list_documents()}


@router.get("/api/admin/tasks")
def admin_tasks(document_id: int | None = None):
    """返回上传、重索引、删除等后台任务记录。"""
    return {"tasks": admin_document_service.list_tasks(document_id)}


@router.get("/api/admin/documents/{document_id}/versions")
def admin_document_versions(document_id: int):
    """查询指定文档的全部版本及其当前激活状态。"""
    versions = admin_document_service.list_versions(document_id)
    if versions is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"versions": versions}


@router.post("/api/admin/documents/{document_id}/versions")
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
    """上传指定文档的新版本，并创建后台处理任务。"""
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


@router.post("/api/admin/documents/{document_id}/disable")
def admin_disable_document(document_id: int):
    """停用指定文档，使其不再参与默认检索。"""
    if not admin_document_service.set_status(document_id, "disabled", None):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"document_id": document_id, "status": "disabled"}


@router.post("/api/admin/documents/{document_id}/restore")
def admin_restore_document(document_id: int):
    """恢复被停用的文档，使文档主状态重新变为可用。"""
    if not admin_document_service.set_status(document_id, "done", None):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"document_id": document_id, "status": "active"}


@router.post("/api/admin/documents/{document_id}/reindex")
def admin_reindex_document(document_id: int):
    """创建文档重新索引任务。"""
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


@router.delete("/api/admin/documents/{document_id}")
def admin_delete_document(document_id: int):
    """创建文档删除任务。"""
    task_id = task_queue.submit(
        "delete",
        document_id,
        lambda _: admin_document_service.delete_document(document_id),
    )
    return {"document_id": document_id, "task_id": task_id, "status": "queued"}


@router.post("/api/admin/documents/{document_id}/activate-version")
def admin_activate_version(document_id: int):
    """把指定版本切换为文档的当前激活版本。"""
    if not admin_document_service.activate_version(document_id, None):
        raise HTTPException(status_code=404, detail="文档版本不存在")
    return {"document_id": document_id, "status": "active"}
