# 上传处理编排：幂等检查 -> 文件哈希 -> 解析 -> 分块 -> 分块去重 -> 写向量库。
# 目前是同步实现，方便理解流程；完善时把 process_upload 搬到异步 worker。

import json
import logging
import re

from fastapi import HTTPException
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from . import config, dedup, models
from .document_loader import load_documents_from_file
from .rag_service import rag_service

logger = logging.getLogger(__name__)


class UploadService:
    def __init__(self, db: Session):
        self.db = db
        # 灰区复核用的 LLM，延迟初始化，避免没有灰区样本时创建客户端。
        self._judge_llm = None

    def process_upload(
        self,
        upload_id: str,
        filename: str,
        content: bytes,
        uploaded_by_user_id: int | None = None,
        uploader_name: str | None = None,
        document_id: str | None = None,
        replace_source_file_id: int | None = None,
        document_metadata: dict | None = None,
    ) -> dict:
        """处理一次上传，返回本次新增/跳过的分块数量。"""
        job = self._get_or_create_job(upload_id)
        document_metadata = self._normalize_document_metadata(
            document_metadata or {},
            filename=filename,
        )

        # 已完成的任务直接返回，实现接口幂等。
        if job.status == "done":
            return {
                "idempotent": True,
                "added": 0,
                "skipped": 0,
                "source_file_id": job.source_file_id,
            }

        # TODO: processing 状态在并发/重试场景下需要分布式锁或队列保证只处理一次。
        job.status = "processing"

        # 第 1 层去重：文件内容哈希。
        file_hash = dedup.file_hash(content)
        target_source = (
            self.db.get(models.SourceFile, replace_source_file_id)
            if replace_source_file_id is not None
            else None
        )
        target_document_id = (
            target_source.document_id
            if target_source is not None
            else document_id
        )
        existing_file = self.db.query(models.SourceFile).filter_by(hash=file_hash).first()
        if existing_file is not None:
            # 只有处理成功的文件才算“已存在”；失败文件允许重试。
            if existing_file.status == "done":
                if (
                    target_source is not None
                    and existing_file.document_id == target_document_id
                ):
                    self._apply_document_metadata(existing_file, document_metadata)
                    self._activate_version(existing_file, target_document_id)
                job.status = "done"
                job.source_file_id = existing_file.id
                self.db.commit()
                return {
                    "skipped_file": True,
                    "added": 0,
                    "skipped": 0,
                    "source_file_id": existing_file.id,
                }

            # 上一次失败/中断：清理残留分块后复用原文件记录重试。
            self._cleanup_failed_file(existing_file)
            source_file = existing_file
            source_file.file_name = filename
            source_file.file_size = len(content)
            source_file.status = "processing"
            source_file.updated_by_user_id = uploaded_by_user_id
            source_file.uploader_name = source_file.uploader_name or uploader_name
            self._apply_document_metadata(source_file, document_metadata)
            self.db.commit()
        else:
            if target_document_id:
                versions = [
                    row[0]
                    for row in self.db.query(models.SourceFile.version)
                    .filter_by(document_id=target_document_id)
                    .all()
                ]
                max_version = max(versions or [0])
                version = max_version + 1
            else:
                target_document_id = f"doc-{file_hash[:16]}"
                version = 1
            source_file = models.SourceFile(
                hash=file_hash,
                file_name=filename,
                file_size=len(content),
                document_id=target_document_id,
                version=version,
                version_status="staging" if target_source is not None else "active",
                is_current=target_source is None,
                uploaded_by_user_id=uploaded_by_user_id,
                uploader_name=uploader_name,
                status="processing",
            )
            self.db.add(source_file)
            self.db.flush()
            self._apply_document_metadata(source_file, document_metadata)
            self.db.flush()

        try:
            # 新链路已经完成结构分析、规则分块和必要的 LLM 兜底。
            chunks = load_documents_from_file(filename, content)
            candidates = []
            skipped = 0
            seen_hashes: set[str] = set()

            # 第 2 层去重：分块内容哈希（完全相同的内容）。
            for doc in chunks:
                hash_text = doc.page_content
                if target_source is not None or source_file.version > 1:
                    hash_text = f"{source_file.document_id}|v{source_file.version}|{doc.page_content}"
                content_hash = dedup.chunk_hash(hash_text)
                # 同一文件内也可能出现重复的短条文，必须先做批次内去重，
                # 否则并发/连续 flush 会触发 content_hash 唯一约束。
                if content_hash in seen_hashes:
                    skipped += 1
                    continue
                exists = self.db.query(models.Chunk).filter_by(content_hash=content_hash).first()
                if exists is not None:
                    skipped += 1
                    continue
                seen_hashes.add(content_hash)
                doc.metadata["content_hash"] = content_hash
                doc.metadata["document_id"] = source_file.document_id
                doc.metadata["version"] = source_file.version
                doc.metadata["version_status"] = source_file.version_status
                doc.metadata.update(
                    {
                        "document_title": source_file.document_title
                        or source_file.file_name,
                        "document_number": source_file.document_number or "",
                        "document_type": source_file.document_type or "",
                        "issuing_department": source_file.issuing_department or "",
                        "effective_date": source_file.effective_date or "",
                        "expiry_date": source_file.expiry_date or "",
                        "supersedes": source_file.supersedes or "",
                        "applicability": source_file.applicability or "",
                        "document_aliases": source_file.document_aliases or "",
                        "is_current": bool(source_file.is_current),
                    }
                )
                candidates.append(doc)

            # 第 3 层去重：语义相似内容。
            # 先批量计算候选分块向量，再用 ANN 查询最相似的已有分块。
            new_docs = []
            added = 0
            if candidates:
                vectors = rag_service.embeddings.embed_documents(
                    [doc.page_content for doc in candidates]
                )
                for doc, vector in zip(candidates, vectors):
                    duplicate = self._find_semantic_duplicate(vector, doc.page_content)
                    if duplicate is not None:
                        canonical_id, similarity = duplicate
                        # 语义重复：保留来源记录，但不写入向量库。
                        self.db.add(
                    models.Chunk(
                        content_hash=doc.metadata["content_hash"],
                        source_file_id=source_file.id,
                        content=doc.page_content,
                        duplicate_of_id=canonical_id,
                        similarity=similarity,
                        logical_hash=doc.metadata.get("logical_hash"),
                        parent_key=doc.metadata.get("parent_key"),
                        parent_id=doc.metadata.get("parent_id"),
                        parent_type=doc.metadata.get("parent_type"),
                        parent_order_index=doc.metadata.get("parent_order_index"),
                        node_type=doc.metadata.get("chunk_strategy") or "child",
                        section_path=doc.metadata.get("section_path"),
                        order_index=doc.metadata.get("order_index"),
                        page_start=doc.metadata.get("page_start"),
                        page_end=doc.metadata.get("page_end"),
                        parser_version=doc.metadata.get("parser_version"),
                        chunker_version=doc.metadata.get("chunker_version"),
                    )
                )
                        skipped += 1
                        continue

                    chunk = models.Chunk(
                        content_hash=doc.metadata["content_hash"],
                        source_file_id=source_file.id,
                        content=doc.page_content,
                        logical_hash=doc.metadata.get("logical_hash"),
                        parent_key=doc.metadata.get("parent_key"),
                        parent_id=doc.metadata.get("parent_id"),
                        parent_type=doc.metadata.get("parent_type"),
                        parent_order_index=doc.metadata.get("parent_order_index"),
                        node_type=doc.metadata.get("chunk_strategy") or "child",
                        section_path=doc.metadata.get("section_path"),
                        order_index=doc.metadata.get("order_index"),
                        page_start=doc.metadata.get("page_start"),
                        page_end=doc.metadata.get("page_end"),
                        parser_version=doc.metadata.get("parser_version"),
                        chunker_version=doc.metadata.get("chunker_version"),
                    )
                    self.db.add(chunk)
                    self.db.flush()
                    # 把数据库主键写入 metadata，向量命中后可反查 canonical chunk。
                    doc.metadata["chunk_id"] = chunk.id
                    doc.metadata["source_file_id"] = source_file.id
                    new_docs.append(doc)
                    added += 1

            self.db.commit()

            if new_docs:
                vector_ids = rag_service.add_documents(new_docs)
                # 回填 vector_id，便于后续删除 / 清理向量。
                for doc, vector_id in zip(new_docs, vector_ids):
                    chunk_id = doc.metadata.get("chunk_id")
                    if chunk_id and vector_id:
                        self.db.query(models.Chunk).filter_by(id=chunk_id).update(
                            {"vector_id": vector_id}
                        )
                self.db.commit()

            # TODO: 向量库写入失败时的补偿策略（重试队列、标记脏数据等）。
            source_file.status = "done"
            source_file.version_status = "active"
            source_file.is_current = True
            if source_file.document_id:
                self.db.query(models.SourceFile).filter(
                    models.SourceFile.document_id == source_file.document_id,
                    models.SourceFile.id != source_file.id,
                ).update(
                    {
                        "is_current": False,
                        "version_status": "retired",
                    },
                    synchronize_session=False,
                )
            job.status = "done"
            job.progress = 100
            job.source_file_id = source_file.id
            self.db.commit()
            return {"added": added, "skipped": skipped, "source_file_id": source_file.id}

        except Exception as exc:
            # 先回滚失败事务，否则后续状态更新会触发 PendingRollbackError。
            self.db.rollback()
            failed_job = self.db.query(models.UploadJob).filter_by(upload_id=upload_id).first()
            failed_file = self.db.query(models.SourceFile).filter_by(hash=file_hash).first()
            if failed_file is not None:
                failed_file.status = "failed"
            if failed_job is not None:
                failed_job.status = "failed"
                failed_job.error = str(exc)
            self.db.commit()
            raise HTTPException(status_code=400, detail=f"处理失败: {exc}") from exc

    def _activate_version(self, source_file: models.SourceFile, document_id: str) -> None:
        self.db.query(models.SourceFile).filter_by(document_id=document_id).update(
            {"is_current": False, "version_status": "retired"},
            synchronize_session=False,
        )
        source_file.is_current = True
        source_file.version_status = "active"
        source_file.status = "done"
        self.db.commit()

    @staticmethod
    def _normalize_document_metadata(metadata: dict, filename: str) -> dict:
        allowed_keys = {
            "document_title",
            "document_number",
            "document_type",
            "issuing_department",
            "effective_date",
            "expiry_date",
            "supersedes",
            "applicability",
            "document_aliases",
        }
        normalized: dict[str, str] = {}
        for key in allowed_keys:
            value = metadata.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                normalized[key] = text
        normalized.setdefault("document_title", filename)
        return normalized

    @staticmethod
    def _apply_document_metadata(
        source_file: models.SourceFile,
        metadata: dict[str, str],
    ) -> None:
        for key, value in metadata.items():
            setattr(source_file, key, value)

    def _find_semantic_duplicate(self, vector, candidate_text: str) -> tuple[int, float] | None:
        """查找与候选向量语义重复的已有分块。

        Chroma 使用 cosine 距离时：similarity = 1 - distance。
        - 高于高置信阈值：直接判定重复；
        - 落在灰区：交给 LLM 复核；
        - 低于灰区下限：视为新内容。
        """
        if not config.SEMANTIC_DEDUP_ENABLED:
            return None
        try:
            results = rag_service.vectorstore.similarity_search_by_vector_with_relevance_scores(
                vector,
                k=config.SEMANTIC_DEDUP_TOP_K,
            )
        except Exception:
            # 向量库为空或版本不支持时，退化为“不做语义去重”。
            return None

        for doc, score in results:
            # langchain_chroma 返回的是 cosine 距离（越小越相近），
            # 相似度 = 1 - 距离。
            similarity = 1 - float(score)
            chunk_id = doc.metadata.get("chunk_id")
            if not chunk_id:
                continue
            if similarity >= config.SEMANTIC_DEDUP_THRESHOLD:
                logger.info("语义去重命中（高置信）similarity=%.4f chunk_id=%s", similarity, chunk_id)
                return int(chunk_id), similarity
            if similarity >= config.SEMANTIC_DEDUP_GRAY_LOW and config.SEMANTIC_DEDUP_LLM_CONFIRM:
                confirmed = self._llm_confirms_duplicate(candidate_text, doc.page_content)
                logger.info(
                    "语义去重灰区复核 similarity=%.4f chunk_id=%s confirmed=%s",
                    similarity,
                    chunk_id,
                    confirmed,
                )
                if confirmed:
                    return int(chunk_id), similarity
        return None

    def _get_judge_llm(self) -> ChatOpenAI:
        """构建灰区复核模型；使用非推理模型保证 JSON 输出稳定。"""
        if self._judge_llm is None:
            self._judge_llm = ChatOpenAI(
                model=config.SEMANTIC_DEDUP_JUDGE_MODEL,
                api_key=config.LLM_API_KEY,
                base_url=config.LLM_BASE_URL,
                temperature=0,
                max_tokens=200,
                timeout=60,
                max_retries=1,
            )
        return self._judge_llm

    def _llm_confirms_duplicate(self, candidate_text: str, existing_text: str) -> bool:
        """灰区复核：判断候选内容是否已被已有内容覆盖。

        去重语义是“包含”而不是“等价”：
        - 已有内容覆盖候选的关键信息 -> 候选冗余，可去重；
        - 候选包含已有内容没有的信息 -> 保留候选，避免丢信息。
        为避免误删，只有模型明确返回 duplicate=true 才判定重复；
        任何异常或解析失败都按“不重复”处理。
        """
        prompt = """你是知识库去重审核员。请判断【内容A】的关键信息是否已经被【内容B】覆盖。

要求：
- 忽略排版、标点、表述顺序差异。
- 如果内容B已经覆盖内容A的核心规定或事实，返回 true，即使B更详细或有额外内容。
- 如果内容A包含内容B没有的关键信息，返回 false，避免丢失信息。
- 如果只是主题相关但规定不同，返回 false。
- 只输出 JSON，不要输出其他内容：{{"duplicate": true, "reason": "不超过30字"}}

【内容A】
{candidate}

【内容B】
{existing}
""".format(candidate=candidate_text, existing=existing_text)

        try:
            response = self._get_judge_llm().invoke(prompt)
            content = getattr(response, "content", "") or ""
            match = re.search(r"\{.*\}", content, re.S)
            if not match:
                return False
            data = json.loads(match.group(0))
            return bool(data.get("duplicate", False))
        except Exception:
            # 复核失败时宁可保留内容，避免误删。
            return False

    def _cleanup_failed_file(self, source_file: models.SourceFile):
        """清理失败文件留下的分块与可能存在的向量，允许重新入库。"""
        chunks = self.db.query(models.Chunk).filter_by(source_file_id=source_file.id).all()
        hashes = [chunk.content_hash for chunk in chunks]
        if hashes:
            try:
                rag_service.vectorstore.delete(where={"content_hash": {"$in": hashes}})
            except Exception:
                # 向量不存在或版本不支持 where 删除时忽略，继续清理数据库。
                pass
        self.db.query(models.Chunk).filter_by(source_file_id=source_file.id).delete()
        self.db.commit()

    def _get_or_create_job(self, upload_id: str) -> models.UploadJob:
        """按幂等键查找任务，不存在则创建。"""
        job = self.db.query(models.UploadJob).filter_by(upload_id=upload_id).first()
        if job is not None:
            return job
        job = models.UploadJob(upload_id=upload_id)
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job
