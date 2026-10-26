"""证据范围、版本过滤、父块与相邻块扩展。"""

from typing import Any, List, cast

from langchain_core.documents import Document

from .. import config
from ..answer_validator import answer_validator
from ..db import SessionLocal
from ..models import SourceFile
from ..parenting import select_parent_window, should_expand_neighbors
from ..query_planner import QueryPlan
from ..retrieval_scope import (
    RetrievalScope,
    select_applicability_sources,
    select_source_ids,
)
from .runtime import RagRuntime


class RagEvidence:
    """把候选分块整理成可引用、可扩展的上下文证据。"""

    def __init__(self, runtime: RagRuntime) -> None:
        self.runtime = runtime

    @staticmethod
    def build_applicability_notice(scope: RetrievalScope) -> str:
        """Build a user-visible warning when the source applicability differs."""
        source = scope.applicability_title or "当前知识库文件"
        applicability = scope.applicability or "未配置"
        if scope.applicability_mode == "fallback":
            cohort = scope.user_cohort or "你所在的年级"
            if cohort.isdigit():
                cohort = f"{cohort}级"
            return (
                f"当前知识库未收录{cohort}适用的文件。以下依据"
                f"《{source}》（适用对象：{applicability}）提供往届参考，"
                "具体规定请以学校发布的最新正式文件为准。\n\n"
            )
        if scope.applicability_mode == "latest_current":
            return (
                f"你未说明所在年级。以下依据当前知识库中的最新文件"
                f"《{source}》（适用对象：{applicability}）回答；"
                "如你的年级不同，请补充年级后核对。\n\n"
            )
        if scope.applicability_mode == "none":
            return "当前知识库没有找到可用于回答该问题的文件。\n\n"
        return ""

    def exclude_disabled_documents(
        self,
        documents: List[Document],
        query_plan: dict | None = None,
        scope: RetrievalScope | None = None,
    ) -> List[Document]:
        if not documents:
            return documents
        scope = scope or self.resolve_retrieval_scope(query_plan or {})
        return [
            document
            for document in documents
            if document.metadata.get("source_file_id") in scope.allowed_source_ids
        ]

    def resolve_retrieval_scope(
        self,
        query_plan: dict | None = None,
    ) -> RetrievalScope:
        """Resolve effective source files once for the whole request."""
        query_plan = query_plan or {}
        time_intent = str(query_plan.get("time_intent") or "current")
        as_of_date = str(query_plan.get("as_of_date") or "")
        with SessionLocal() as db:
            query = db.query(
                SourceFile.id,
                SourceFile.document_id,
                SourceFile.version,
                SourceFile.effective_date,
                SourceFile.is_current,
                SourceFile.applicability,
                SourceFile.document_title,
                SourceFile.file_name,
            ).filter(SourceFile.status == "done")
            if time_intent == "current":
                query = query.filter(
                    SourceFile.version_status == "active",
                    SourceFile.is_current.is_(True),
                )
            rows = query.all()
            active_ids = self._select_source_ids(
                rows,
                time_intent=time_intent,
                as_of_date=as_of_date,
            )
        applicability_selection = select_applicability_sources(
            rows,
            active_ids,
            user_cohort=str(query_plan.get("user_cohort") or ""),
            preserve_all_without_cohort=time_intent in {"historical", "compare"},
        )
        selected_ids = (
            set(applicability_selection.source_ids)
            if applicability_selection.source_ids
            else set()
        )
        return RetrievalScope(
            allowed_source_ids=frozenset(selected_ids),
            time_intent=time_intent,
            as_of_date=as_of_date,
            user_cohort=str(query_plan.get("user_cohort") or ""),
            applicability_mode=applicability_selection.mode,
            applicability=applicability_selection.applicability,
            applicability_title=applicability_selection.title,
        )

    @staticmethod
    def _select_source_ids(
        rows: list,
        time_intent: str,
        as_of_date: str,
    ) -> set[int]:
        return select_source_ids(rows, time_intent, as_of_date)

    @staticmethod
    def enrich_document_metadata(documents: List[Document]) -> List[Document]:
        if not documents:
            return documents
        source_ids = {
            int(document.metadata["source_file_id"])
            for document in documents
            if str(document.metadata.get("source_file_id", "")).isdigit()
        }
        if not source_ids:
            return documents

        with SessionLocal() as db:
            sources = (
                db.query(SourceFile)
                .filter(SourceFile.id.in_(source_ids))
                .all()
            )
        source_map = {int(source.id): source for source in sources}
        for document in documents:
            raw_source_file_id = document.metadata.get("source_file_id")
            if raw_source_file_id is None:
                continue
            try:
                source_file_id = int(raw_source_file_id)
            except (TypeError, ValueError):
                continue
            source = source_map.get(source_file_id)
            if source is None:
                continue
            document.metadata.update(
                {
                    "document_id": source.document_id or "",
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
                }
            )
        return documents

    def fill_evidence_coverage(
        self,
        documents: List[Document],
        query_plan: QueryPlan,
        scope: RetrievalScope | None = None,
    ) -> List[Document]:
        if (
            not config.EVIDENCE_COVERAGE_ENABLED
            or self.runtime.bm25_retriever is None
            or len(query_plan.subquestions) <= 1
            or not documents
        ):
            return documents

        coverage = answer_validator.build_coverage(query_plan.subquestions, documents)
        missing = coverage.get("missing_subquestions", [])[
            : config.EVIDENCE_COVERAGE_MAX_SUBQUESTIONS
        ]
        if not missing:
            return documents

        merged = list(documents)
        seen = {self._document_key(document) for document in documents}
        scores = [
            float(document.metadata.get("rerank_score", 0.0) or 0.0)
            for document in documents
        ]
        fallback_score = max(0.0, (min(scores) if scores else 0.5) - 0.05)
        added = 0
        scope = scope or self.resolve_retrieval_scope(query_plan.to_dict())

        for subquestion in missing:
            try:
                candidates = self.runtime.bm25_retriever.invoke(subquestion)
            except Exception:
                continue
            candidates = self.exclude_disabled_documents(
                candidates,
                scope=scope,
            )
            for candidate in candidates[: config.EVIDENCE_COVERAGE_TOP_K]:
                key = self._document_key(candidate)
                if key in seen:
                    continue
                candidate.metadata["coverage_fill"] = True
                candidate.metadata["matched_subquestion"] = subquestion
                candidate.metadata["rerank_score"] = fallback_score
                merged.append(candidate)
                seen.add(key)
                added += 1
                if added >= config.EVIDENCE_COVERAGE_MAX_ADDED:
                    return merged
        return merged

    @staticmethod
    def _document_key(document: Document) -> str:
        return str(
            document.metadata.get("chunk_id")
            or document.metadata.get("content_hash")
            or document.page_content
        )

    def expand_parent_chunks(self, docs: List[Document]) -> List[Document]:
        """按 parent_id/parent_key 带出命中子块的同父级上下文。"""
        if not config.PARENT_EXPANSION_ENABLED or not docs:
            return docs

        expanded = list(docs)
        seen = {
            doc.metadata.get("chunk_id") or doc.metadata.get("content_hash") or doc.page_content
            for doc in docs
        }
        added = 0

        for document in docs:
            parent_id = document.metadata.get("parent_id")
            parent_key = document.metadata.get("parent_key")
            if not parent_id and not parent_key:
                continue

            filters = []
            source_file_id = document.metadata.get("source_file_id")
            if isinstance(source_file_id, int):
                filters.append({"source_file_id": {"$eq": source_file_id}})
            if parent_id:
                filters.append({"parent_id": {"$eq": parent_id}})
            else:
                filters.append({"parent_key": {"$eq": parent_key}})

            where = filters[0] if len(filters) == 1 else {"$and": filters}
            try:
                result = self.runtime.vectorstore.get(
                    where=cast(Any, where),
                    include=["documents", "metadatas"],
                )
            except Exception:
                continue

            candidates = [
                Document(page_content=content, metadata=dict(metadata or {}))
                for content, metadata in zip(
                    result.get("documents", []),
                    result.get("metadatas", []),
                )
            ]
            if len(candidates) <= 1:
                continue

            window = select_parent_window(
                candidates,
                document,
                max_chars=config.PARENT_EXPANSION_MAX_CHARS,
                max_children=config.PARENT_EXPANSION_MAX_CHILDREN,
            )
            for candidate in window:
                key = (
                    candidate.metadata.get("chunk_id")
                    or candidate.metadata.get("content_hash")
                    or candidate.page_content
                )
                if key in seen:
                    continue
                document.metadata["parent_expansion_applied"] = True
                candidate.metadata["expanded_parent"] = True
                candidate.metadata["expanded_from_chunk_id"] = document.metadata.get("chunk_id")
                expanded.append(candidate)
                seen.add(key)
                added += 1
                if added >= config.PARENT_EXPANSION_MAX_ADDED:
                    return expanded

        return expanded

    def expand_neighboring_chunks(self, docs: List[Document]) -> List[Document]:
        """带出命中分块前后的同文件分块，避免条文被切在相邻块中。"""
        if not config.NEIGHBOR_EXPANSION_ENABLED or not docs:
            return docs

        expanded = list(docs)
        seen = {
            doc.metadata.get("chunk_id") or doc.page_content
            for doc in docs
        }
        added = 0

        for document in docs:
            if not should_expand_neighbors(
                document,
                conditional=config.NEIGHBOR_CONDITIONAL_ENABLED,
            ):
                continue
            source_file_id = document.metadata.get("source_file_id")
            order_index = document.metadata.get("order_index")
            if not isinstance(source_file_id, int) or not isinstance(order_index, int):
                continue

            start = max(0, order_index - config.NEIGHBOR_EXPANSION_WINDOW)
            end = order_index + config.NEIGHBOR_EXPANSION_WINDOW
            try:
                result = self.runtime.vectorstore.get(
                    where={
                        "$and": [
                            {"source_file_id": {"$eq": source_file_id}},
                            {"order_index": {"$gte": start}},
                            {"order_index": {"$lte": end}},
                        ]
                    },
                    include=["documents", "metadatas"],
                )
            except Exception:
                # 旧数据没有 order_index，或向量库不支持组合过滤时保持原结果。
                continue

            neighbors = []
            for content, metadata in zip(result.get("documents", []), result.get("metadatas", [])):
                metadata = dict(metadata or {})
                if metadata.get("order_index") is None:
                    continue
                neighbors.append(Document(page_content=content, metadata=metadata))

            for neighbor in sorted(neighbors, key=lambda item: int(item.metadata.get("order_index", 0))):
                key = neighbor.metadata.get("chunk_id") or neighbor.page_content
                if key in seen:
                    continue
                neighbor.metadata["expanded_neighbor"] = True
                neighbor.metadata["expanded_from_chunk_id"] = document.metadata.get("chunk_id")
                expanded.append(neighbor)
                seen.add(key)
                added += 1
                if added >= config.NEIGHBOR_EXPANSION_MAX_ADDED:
                    return expanded

        return expanded
