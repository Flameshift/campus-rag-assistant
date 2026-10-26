"""知识库上传与任务状态接口。"""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .. import dedup, models
from ..db import SessionLocal
from ..schemas import UploadResponse
from ..upload_service import UploadService

router = APIRouter()


@router.post("/api/upload", response_model=UploadResponse)
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
    """上传并索引一份新资料。"""
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


@router.get("/api/jobs/{upload_id}")
def job_status(upload_id: str):
    """查询上传、版本更新、重索引或删除任务的状态。"""
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
