"""管理员文档管理服务。"""

import uuid
from datetime import datetime, timezone

from langchain_core.documents import Document

from . import models
from .db import SessionLocal
from .rag_service import rag_service


def _format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def _display_status(status: str) -> str:
    return {
        "done": "active",
        "processing": "processing",
        "pending": "processing",
        "disabled": "disabled",
        "failed": "failed",
    }.get(status, status)


class AdminDocumentService:
    def list_documents(self) -> list[dict]:
        with SessionLocal() as db:
            source_files = (
                db.query(models.SourceFile)
                .filter(models.SourceFile.is_current.is_(True))
                .order_by(models.SourceFile.created_at.desc())
                .all()
            )
            result = []
            for source in source_files:
                chunks = db.query(models.Chunk).filter_by(source_file_id=source.id).all()
                parents = {chunk.parent_id for chunk in chunks if chunk.parent_id}
                result.append(
                    {
                        "id": str(source.id),
                        "name": source.file_name,
                        "documentTitle": source.document_title or source.file_name,
                        "documentNumber": source.document_number or "",
                        "documentType": source.document_type or "",
                        "issuingDepartment": source.issuing_department or "",
                        "effectiveDate": source.effective_date or "",
                        "applicability": source.applicability or "",
                        "type": source.file_name.rsplit(".", 1)[-1].upper(),
                        "version": f"v{source.version}",
                        "status": _display_status(source.status),
                        "chunks": len(chunks),
                        "parents": len(parents),
                        "size": _format_size(source.file_size),
                        "updatedAt": (source.updated_at or source.created_at).strftime(
                            "%Y-%m-%d %H:%M"
                        ),
                        "owner": source.uploader_name or "系统历史数据",
                        "uploadedByUserId": source.uploaded_by_user_id,
                    }
                )
            return result

    def list_tasks(self, document_id: int | None = None) -> list[dict]:
        with SessionLocal() as db:
            query = db.query(models.UploadJob)
            if document_id is not None:
                query = query.filter_by(source_file_id=document_id)
            jobs = query.order_by(models.UploadJob.created_at.desc()).limit(200).all()
            source_ids = [job.source_file_id for job in jobs if job.source_file_id]
            sources = {
                source.id: source
                for source in db.query(models.SourceFile)
                .filter(models.SourceFile.id.in_(source_ids))
                .all()
            } if source_ids else {}
            return [
                {
                    "id": job.upload_id,
                    "documentId": str(job.source_file_id) if job.source_file_id else "",
                    "document": sources[job.source_file_id].file_name
                    if job.source_file_id in sources
                    else "",
                    "type": "上传/索引",
                    "taskType": job.task_type,
                    "status": (
                        "completed"
                        if job.status == "done"
                        else "running"
                        if job.status in {"queued", "processing"}
                        else "failed"
                    ),
                    "stage": job.status,
                    "progress": job.progress
                    if job.progress
                    else 100 if job.status == "done" else 50 if job.status == "processing" else 0,
                    "startedAt": job.created_at.strftime("%Y-%m-%d %H:%M"),
                    "message": job.error or ("任务已完成" if job.status == "done" else "处理中"),
                }
                for job in jobs
            ]

    def set_status(self, document_id: int, status: str, user_id: int | None) -> bool:
        with SessionLocal() as db:
            source = db.get(models.SourceFile, document_id)
            if source is None:
                return False
            source.status = status
            source.updated_by_user_id = user_id
            source.updated_at = datetime.now(timezone.utc)
            db.commit()
            return True

    def delete_document(self, document_id: int) -> bool:
        with SessionLocal() as db:
            source = db.get(models.SourceFile, document_id)
            if source is None:
                return False
            versions = (
                db.query(models.SourceFile)
                .filter_by(document_id=source.document_id)
                .all()
            )
            source_ids = [version.id for version in versions]
            for source_id in source_ids:
                try:
                    rag_service.delete_vectors(
                        where={"source_file_id": {"$eq": source_id}}
                    )
                except Exception:
                    pass
            db.query(models.Chunk).filter(models.Chunk.source_file_id.in_(source_ids)).delete(
                synchronize_session=False
            )
            db.query(models.UploadJob).filter(
                models.UploadJob.source_file_id.in_(source_ids)
            ).delete(synchronize_session=False)
            for version in versions:
                db.delete(version)
            db.commit()
        rag_service.refresh_retriever()
        return True

    def reindex_document(
        self,
        document_id: int,
        user_id: int | None,
        task_id: str | None = None,
    ) -> str | None:
        with SessionLocal() as db:
            source = db.get(models.SourceFile, document_id)
            if source is None:
                return None
            chunks = (
                db.query(models.Chunk)
                .filter_by(source_file_id=document_id)
                .order_by(models.Chunk.order_index.asc())
                .all()
            )
            documents = [
                Document(
                    page_content=chunk.content,
                    metadata={
                        "chunk_id": chunk.id,
                        "source_file_id": document_id,
                        "source": source.file_name,
                        "document_id": source.document_id,
                        "document_title": source.document_title or source.file_name,
                        "document_number": source.document_number or "",
                        "document_type": source.document_type or "",
                        "issuing_department": source.issuing_department or "",
                        "effective_date": source.effective_date or "",
                        "expiry_date": source.expiry_date or "",
                        "supersedes": source.supersedes or "",
                        "applicability": source.applicability or "",
                        "document_aliases": source.document_aliases or "",
                        "version": source.version,
                        "version_status": source.version_status,
                        "is_current": bool(source.is_current),
                        "content_hash": chunk.content_hash,
                        "logical_hash": chunk.logical_hash,
                        "parent_key": chunk.parent_key,
                        "parent_id": chunk.parent_id,
                        "parent_type": chunk.parent_type,
                        "parent_order_index": chunk.parent_order_index,
                        "chunk_strategy": chunk.node_type,
                        "section_path": chunk.section_path,
                        "order_index": chunk.order_index,
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                        "parser_version": chunk.parser_version,
                        "chunker_version": chunk.chunker_version,
                    },
                )
                for chunk in chunks
                if chunk.duplicate_of_id is None
            ]
            if not documents:
                return None

            task_id = task_id or f"reindex-{uuid.uuid4().hex[:12]}"
            task = db.query(models.UploadJob).filter_by(upload_id=task_id).first()
            if task is None:
                task = models.UploadJob(
                    upload_id=task_id,
                    source_file_id=document_id,
                    task_type="reindex",
                    status="processing",
                )
                db.add(task)
                db.commit()

            try:
                rag_service.delete_vectors(
                    where={"source_file_id": {"$eq": document_id}}
                )
                vector_ids = rag_service.add_documents(documents)
                for document, vector_id in zip(documents, vector_ids):
                    chunk_id = document.metadata.get("chunk_id")
                    if chunk_id and vector_id:
                        db.query(models.Chunk).filter_by(id=chunk_id).update(
                            {"vector_id": vector_id}
                        )
                source.status = "done"
                source.updated_by_user_id = user_id
                source.updated_at = datetime.now(timezone.utc)
                task.status = "done"
                db.commit()
                rag_service.refresh_retriever()
                return task_id
            except Exception as exc:
                task.status = "failed"
                task.error = str(exc)
                source.status = "failed"
                db.commit()
                raise

    def list_versions(self, document_id: int) -> list[dict] | None:
        with SessionLocal() as db:
            source = db.get(models.SourceFile, document_id)
            if source is None:
                return None
            versions = (
                db.query(models.SourceFile)
                .filter_by(document_id=source.document_id)
                .order_by(models.SourceFile.version.desc())
                .all()
            )
            return [
                {
                    "id": str(version.id),
                    "documentId": version.document_id,
                    "documentTitle": version.document_title or version.file_name,
                    "documentNumber": version.document_number or "",
                    "version": version.version,
                    "status": version.version_status,
                    "current": version.is_current,
                    "name": version.file_name,
                    "uploader": version.uploader_name or "系统历史数据",
                    "createdAt": version.created_at.strftime("%Y-%m-%d %H:%M"),
                }
                for version in versions
            ]

    def activate_version(self, source_file_id: int, user_id: int | None) -> bool:
        with SessionLocal() as db:
            source = db.get(models.SourceFile, source_file_id)
            if source is None:
                return False
            db.query(models.SourceFile).filter_by(document_id=source.document_id).update(
                {"is_current": False, "version_status": "retired"},
                synchronize_session=False,
            )
            source.is_current = True
            source.version_status = "active"
            source.status = "done"
            source.updated_by_user_id = user_id
            source.updated_at = datetime.now(timezone.utc)
            db.commit()
            return True


admin_document_service = AdminDocumentService()
