"""RAG 模型、向量库和检索器初始化。"""

import threading
import time
from pathlib import Path
from typing import Any, Dict, List, cast

import jieba
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings, FakeEmbeddings
from langchain_core.retrievers import BaseRetriever
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr

from .. import config
from ..embedding_batching import BoundedBatchEmbeddings
from ..ingestion.service import ingestion_service
from .observability import record_timing


class TimedEmbeddings(Embeddings):
    """包装 Embedding，记录查询向量化和文档向量化耗时。"""

    def __init__(self, delegate: Embeddings) -> None:
        self.delegate = delegate

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        started_at = time.perf_counter()
        vectors = self.delegate.embed_documents(texts)
        record_timing("embedding_documents_ms", started_at)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        started_at = time.perf_counter()
        vector = self.delegate.embed_query(text)
        record_timing("query_embedding_ms", started_at)
        return vector


class RagRuntime:
    """负责外部模型、Chroma、知识库写入和混合检索器的生命周期。"""

    def __init__(self) -> None:
        self.use_fake = not (config.EMBEDDING_API_KEY and config.LLM_API_KEY)
        self.embeddings = self._build_embeddings()
        self.vectorstore = self._build_vectorstore()
        self.vector_retriever: BaseRetriever = self.vectorstore.as_retriever(
            search_kwargs={"k": config.RETRIEVE_CANDIDATES}
        )
        self._retriever_lock = threading.Lock()
        self.bm25_retriever: BM25Retriever | None = None
        self.retriever: BaseRetriever = self.vector_retriever
        self._build_hybrid_retriever()
        self.llm = self._build_llm()

    def _build_embeddings(self):
        """构建向量化器，演示模式使用 FakeEmbeddings。"""
        if self.use_fake:
            delegate = FakeEmbeddings(size=256)
        else:
            delegate = OpenAIEmbeddings(
                model=config.EMBEDDING_MODEL,
                api_key=SecretStr(config.EMBEDDING_API_KEY),
                base_url=config.EMBEDDING_BASE_URL,
                check_embedding_ctx_length=False,
                chunk_size=config.EMBEDDING_BATCH_SIZE,
            )
        return TimedEmbeddings(
            BoundedBatchEmbeddings(
                delegate,
                batch_size=config.EMBEDDING_BATCH_SIZE,
                max_concurrency=config.EMBEDDING_MAX_CONCURRENCY,
            )
        )

    def _build_llm(self):
        """构建大模型客户端；演示模式下返回 None。"""
        if self.use_fake:
            return None
        return ChatOpenAI(
            model=config.LLM_MODEL,
            api_key=SecretStr(config.LLM_API_KEY),
            base_url=config.LLM_BASE_URL,
            temperature=0,
        )

    def _build_vectorstore(self):
        """创建或打开 Chroma 向量库。"""
        persist_dir = Path(config.VECTOR_DB_DIR)
        persist_dir.mkdir(parents=True, exist_ok=True)
        return Chroma(
            persist_directory=str(persist_dir),
            embedding_function=self.embeddings,
            collection_metadata={"hnsw:space": "cosine"},
        )

    @staticmethod
    def _bm25_tokenize(text: str) -> List[str]:
        """中文 BM25 分词。"""
        return list(jieba.cut_for_search(text))

    def _load_chunks_for_bm25(self) -> List[Document]:
        """从 Chroma 读取分块并按内容哈希去重。"""
        data = self.vectorstore.get(include=["documents", "metadatas"])
        documents: List[Document] = []
        seen_hashes = set()
        for content, metadata in zip(data["documents"], data["metadatas"]):
            metadata = metadata or {}
            content_hash = metadata.get("content_hash") or content
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)
            documents.append(Document(page_content=content, metadata=metadata))
        return documents

    def _build_hybrid_retriever(self):
        """构建 BM25 + 向量混合检索器。"""
        if not config.BM25_ENABLED:
            self.bm25_retriever = None
            self.retriever = self.vector_retriever
            return

        documents = self._load_chunks_for_bm25()
        if not documents:
            self.bm25_retriever = None
            self.retriever = self.vector_retriever
            return

        self.bm25_retriever = BM25Retriever.from_documents(
            documents,
            preprocess_func=self._bm25_tokenize,
        )
        self.bm25_retriever.k = config.RETRIEVE_CANDIDATES
        self.retriever = EnsembleRetriever(
            retrievers=[self.bm25_retriever, self.vector_retriever],
            weights=[config.BM25_WEIGHT, config.VECTOR_WEIGHT],
        )

    def refresh_retriever(self):
        """重建混合检索器。"""
        with self._retriever_lock:
            self._build_hybrid_retriever()

    def add_text(self, text: str, metadata: Dict | None = None):
        """把一段文本结构化分块后写入知识库。"""
        docs = ingestion_service.split_text(text, metadata or {})
        return self.add_documents(docs)

    def add_documents(self, documents: List[Document]):
        """把已经分块的 Document 写入向量库。"""
        ids = self.vectorstore.add_documents(documents)
        persist = getattr(self.vectorstore, "persist", None)
        if callable(persist):
            persist()
        self.refresh_retriever()
        return ids

    def knowledge_count(self) -> int:
        """返回知识库当前的分块总数。"""
        return len(self.vectorstore.get()["ids"])

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量计算文本向量，供上传去重和管理操作复用。"""
        return self.embeddings.embed_documents(texts)

    def search_by_vector_with_scores(
        self,
        vector: list[float],
        k: int,
    ) -> list[tuple[Document, float]]:
        """按向量检索并返回文档及相似度分数。"""
        return self.vectorstore.similarity_search_by_vector_with_relevance_scores(
            vector,
            k=k,
        )

    def delete_vectors(self, where: dict[str, Any]) -> None:
        """按 metadata 条件删除向量，由调用方负责随后刷新检索器。"""
        self.vectorstore.delete(where=cast(Any, where))
