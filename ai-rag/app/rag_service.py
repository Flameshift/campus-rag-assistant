"""RAG 对外门面：组装运行时、检索、证据和问答管线。"""

import threading
from collections.abc import Iterator
from typing import Any

from langchain_core.documents import Document

from .rag.cancellation import StreamCancelled
from .rag.evidence import RagEvidence
from .rag.pipeline import RagPipeline
from .rag.retrieval import RagRetrieval
from .rag.runtime import RagRuntime

__all__ = ["RagService", "StreamCancelled", "rag_service"]


class RagService:
    """保持稳定公开接口，内部完全由显式组件协作。"""

    def __init__(self) -> None:
        self.runtime = RagRuntime()
        self.evidence = RagEvidence(self.runtime)
        self.retrieval = RagRetrieval(self.runtime, self.evidence)
        self.pipeline = RagPipeline(self.runtime, self.retrieval)

    @property
    def use_fake(self) -> bool:
        return self.runtime.use_fake

    def add_text(self, text: str, metadata: dict | None = None):
        return self.runtime.add_text(text, metadata)

    def add_documents(self, documents: list[Document]):
        return self.runtime.add_documents(documents)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.runtime.embed_documents(texts)

    def search_by_vector_with_scores(
        self,
        vector: list[float],
        k: int,
    ) -> list[tuple[Document, float]]:
        return self.runtime.search_by_vector_with_scores(vector, k)

    def delete_vectors(self, where: dict[str, Any]) -> None:
        self.runtime.delete_vectors(where)

    def refresh_retriever(self) -> None:
        self.runtime.refresh_retriever()

    def knowledge_count(self) -> int:
        return self.runtime.knowledge_count()

    def chat(
        self,
        question: str,
        history: list[dict],
        thread_id: str | None = None,
        history_trusted: bool = False,
    ) -> tuple[str, list[dict], str, dict[str, float], str, dict[str, Any]]:
        return self.pipeline.chat(
            question,
            history,
            thread_id=thread_id,
            history_trusted=history_trusted,
        )

    def stream_chat(
        self,
        question: str,
        history: list[dict],
        thread_id: str | None = None,
        history_trusted: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[dict]:
        return self.pipeline.stream_chat(
            question,
            history,
            thread_id=thread_id,
            history_trusted=history_trusted,
            cancel_event=cancel_event,
        )


rag_service = RagService()
