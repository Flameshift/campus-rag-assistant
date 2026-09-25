"""请求级 RAG 阶段追踪，用于实验对比和证据链审计。"""

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from . import config


TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\s]")


def estimate_tokens(text: str) -> int:
    """用轻量规则估算上下文规模，避免依赖具体模型 tokenizer。"""
    return len(TOKEN_PATTERN.findall(text or ""))


class RagTrace:
    """记录一次请求的检索、重排、扩展和最终上下文。"""

    def __init__(self, request_id: str | None = None) -> None:
        self.request_id = request_id or uuid.uuid4().hex[:12]
        self.enabled = bool(config.RAG_TRACE_ENABLED)
        self.data: dict[str, Any] = {
            "request_id": self.request_id,
            "stages": {},
            "values": {},
        }

    def record_value(self, name: str, value: Any) -> None:
        if not self.enabled:
            return
        self.data["values"][name] = value

    def record_stage(
        self,
        name: str,
        documents: list[Document] | None = None,
        extra: dict | None = None,
    ) -> None:
        if not self.enabled:
            return
        document_items = [
            self._document_trace(document)
            for document in (documents or [])
        ]
        self.data["stages"][name] = {
            "count": len(document_items),
            "documents": document_items,
            **(extra or {}),
        }

    def record_context(self, name: str, documents: list[Document]) -> None:
        if not self.enabled:
            return
        text = "\n\n".join(document.page_content for document in documents)
        self.record_stage(name, documents)
        self.data["values"][f"{name}_chars"] = len(text)
        self.data["values"][f"{name}_estimated_tokens"] = estimate_tokens(text)

    def save(self) -> Path | None:
        if not self.enabled:
            return None
        trace_dir = Path(config.RAG_TRACE_DIR)
        trace_dir.mkdir(parents=True, exist_ok=True)
        path = trace_dir / f"{self.request_id}.json"
        path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._cleanup_traces(trace_dir, current_path=path)
        return path

    @staticmethod
    def _cleanup_traces(trace_dir: Path, current_path: Path) -> None:
        files = [
            path
            for path in trace_dir.glob("*.json")
            if path.is_file()
        ]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        retained_bytes = 0
        retained_count = 0
        now = time.time()
        retention_seconds = config.RAG_TRACE_RETENTION_DAYS * 24 * 60 * 60

        for path in files:
            if path == current_path:
                retained_count += 1
                retained_bytes += path.stat().st_size
                continue
            stat = path.stat()
            expired = retention_seconds > 0 and now - stat.st_mtime > retention_seconds
            over_count = (
                config.RAG_TRACE_MAX_FILES > 0
                and retained_count >= config.RAG_TRACE_MAX_FILES
            )
            over_size = (
                config.RAG_TRACE_MAX_TOTAL_BYTES > 0
                and retained_bytes + stat.st_size > config.RAG_TRACE_MAX_TOTAL_BYTES
            )
            if expired or over_count or over_size:
                path.unlink(missing_ok=True)
                continue
            retained_count += 1
            retained_bytes += stat.st_size

    @staticmethod
    def _document_trace(document: Document) -> dict:
        metadata = document.metadata or {}
        content = document.page_content or ""
        return {
            "chunk_id": metadata.get("chunk_id"),
            "source_file_id": metadata.get("source_file_id"),
            "parent_id": metadata.get("parent_id"),
            "parent_key": metadata.get("parent_key"),
            "section_path": metadata.get("section_path"),
            "order_index": metadata.get("order_index"),
            "page": metadata.get("page"),
            "page_start": metadata.get("page_start"),
            "page_end": metadata.get("page_end"),
            "rrf_score": metadata.get("rrf_score"),
            "rerank_score": metadata.get("rerank_score"),
            "coverage_fill": bool(metadata.get("coverage_fill")),
            "parent_expansion_applied": bool(
                metadata.get("parent_expansion_applied")
            ),
            "expanded_parent": bool(metadata.get("expanded_parent")),
            "expanded_neighbor": bool(metadata.get("expanded_neighbor")),
            "exact_title_match": bool(metadata.get("exact_title_match")),
            "content_hash": metadata.get("content_hash") or metadata.get("logical_hash"),
            "content_chars": len(content),
            "estimated_tokens": estimate_tokens(content),
        }
