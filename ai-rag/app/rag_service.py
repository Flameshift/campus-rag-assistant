# RAG 核心服务：文档入库、向量检索、答案生成都在这里完成。
#
# 整体流程：
#   文档入库：上传文本 -> 分块 -> 向量化 -> 写入 Chroma
#   用户提问：问题向量化 -> 相似度检索 -> 拼装 Prompt -> LLM 生成回答

import contextvars
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List

import jieba
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.runnables import RunnableLambda
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings, FakeEmbeddings
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from . import config
from .answer_validator import answer_validator
from .answer_verifier import answer_verifier
from .citations import (
    append_source_footer,
    build_evidence_context,
    build_new_source_footer,
)
from .confidence import confidence_evaluator
from .db import SessionLocal
from .embedding_batching import BoundedBatchEmbeddings
from .evidence_selector import boost_quoted_title_matches
from .evidence_objects import build_evidence_objects
from .ingestion.service import ingestion_service
from .models import SourceFile
from .parenting import select_parent_window, should_expand_neighbors
from .prompts import RAG_SYSTEM_PROMPT
from .query_rewriter import QueryRewriter
from .query_planner import QueryPlan, query_planner
from .rag_trace import RagTrace
from .retrieval_scope import (
    RetrievalScope,
    select_applicability_sources,
    select_source_ids,
)
from .reranker import reranker
from .retrieval_fusion import reciprocal_rank_fusion
from .short_term_memory import MemoryContext, short_term_memory

# jieba 首次加载词典时会打印日志，这里只保留警告级别。
jieba.setLogLevel(logging.WARNING)

# 每次请求独立保存阶段耗时，避免并发请求之间互相污染。
_TIMING_CONTEXT: contextvars.ContextVar[dict[str, float] | None] = contextvars.ContextVar(
    "rag_timing_context",
    default=None,
)


def _record_timing(name: str, started_at: float) -> None:
    """把一次子调用的耗时写入当前请求的计时上下文。"""
    metrics = _TIMING_CONTEXT.get()
    if metrics is not None:
        metrics[name] = round((time.perf_counter() - started_at) * 1000, 2)


class TimedEmbeddings(Embeddings):
    """包装 Embedding，记录查询向量化和文档向量化耗时。"""

    def __init__(self, delegate: Embeddings) -> None:
        self.delegate = delegate

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        started_at = time.perf_counter()
        vectors = self.delegate.embed_documents(texts)
        _record_timing("embedding_documents_ms", started_at)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        started_at = time.perf_counter()
        vector = self.delegate.embed_query(text)
        _record_timing("query_embedding_ms", started_at)
        return vector


class RagService:
    """封装 RAG 全流程的服务类，进程内只初始化一次。"""

    def __init__(self):
        # 演示模式判断：未同时配置 LLM 和 Embedding 的 API Key 时启用。
        # 演示模式下检索链路仍可运行，但回答由本地逻辑生成。
        self.use_fake = not (config.EMBEDDING_API_KEY and config.LLM_API_KEY)
        self.embeddings = self._build_embeddings()
        self.vectorstore = self._build_vectorstore()
        # 语义检索器：先召回更多候选，供混合检索融合后使用。
        self.vector_retriever = self.vectorstore.as_retriever(
            search_kwargs={"k": config.RETRIEVE_CANDIDATES}
        )
        # BM25 关键词检索器为内存索引，新增文档后需要重建。
        self._retriever_lock = threading.Lock()
        self.bm25_retriever = None
        self.retriever = self.vector_retriever
        self._build_hybrid_retriever()
        self.llm = self._build_llm()
        self.query_rewriter = QueryRewriter()
        # 提示词模板：把对话历史、参考资料和用户问题组合成最终 Prompt。
        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", RAG_SYSTEM_PROMPT),
                ("human", "对话历史：{history}"),
                ("human", "结合历史后的检索意图：{retrieval_query}"),
                ("human", "用户问题：{question}"),
            ]
        )
        # LCEL 链：整理输入 -> Prompt 模板 -> LLM。
        # 演示模式下不构建真实链，问答时走本地模拟回答。
        self.chat_chain = None
        if self.llm is not None:
            self.chat_chain = (
                RunnableLambda(self._build_prompt_input)
                | self.prompt_template
                | self.llm
            )

    def _build_embeddings(self):
        """构建向量化器。

        演示模式使用 FakeEmbeddings（固定维度随机向量），让本地无 Key 也能跑通；
        正式模式使用 OpenAI 兼容的 embedding 接口。
        """
        if self.use_fake:
            delegate = FakeEmbeddings(size=256)
        else:
            delegate = OpenAIEmbeddings(
                model=config.EMBEDDING_MODEL,
                api_key=config.EMBEDDING_API_KEY,
                base_url=config.EMBEDDING_BASE_URL,
                # 千问兼容接口要求直接传字符串，不能传 token 数组。
                check_embedding_ctx_length=False,
                # 千问限制单次最多 25 条，超过会被接口拒绝。
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
        """构建大模型客户端；演示模式下不加载模型，返回 None。"""
        if self.use_fake:
            return None
        return ChatOpenAI(
            model=config.LLM_MODEL,
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_BASE_URL,
            temperature=0,
        )

    def _build_vectorstore(self):
        """创建或打开 Chroma 向量库，目录不存在时自动创建。"""
        persist_dir = Path(config.VECTOR_DB_DIR)
        persist_dir.mkdir(parents=True, exist_ok=True)
        return Chroma(
            persist_directory=str(persist_dir),
            embedding_function=self.embeddings,
            collection_metadata={"hnsw:space": "cosine"},
        )

    @staticmethod
    def _bm25_tokenize(text: str) -> List[str]:
        """中文 BM25 分词：使用 jieba 搜索模式，兼顾专有名词和短词。"""
        return list(jieba.cut_for_search(text))

    def _load_chunks_for_bm25(self) -> List[Document]:
        """从 Chroma 读取全部分块，按内容哈希去重后用于 BM25 建索引。"""
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
        """构建 BM25 + 向量混合检索器。

        说明：
        - BM25 负责数字、条款、专有名词等精确关键词召回；
        - 向量检索负责语义相近但表述不同的召回；
        - EnsembleRetriever 对两路结果做加权排名融合。
        """
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
        """重建混合检索器，文档新增或删除后调用。"""
        with self._retriever_lock:
            self._build_hybrid_retriever()

    def _retrieve_multi_query_batched(
        self,
        retrieval_queries: list[str],
    ) -> list[list[Document]]:
        """Batch query embeddings, then run per-query hybrid retrieval."""
        embedding_started = time.perf_counter()
        query_vectors = self.embeddings.embed_documents(retrieval_queries)
        _record_timing("query_embedding_batch_ms", embedding_started)
        if len(query_vectors) != len(retrieval_queries):
            raise ValueError("query embedding count does not match query count")

        result_sets: list[list[Document]] = []
        for retrieval_query, query_vector in zip(retrieval_queries, query_vectors):
            vector_documents: list[Document] = []
            try:
                vector_documents = self.vectorstore.similarity_search_by_vector(
                    query_vector,
                    k=config.RETRIEVE_CANDIDATES,
                )
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "批量查询向量召回失败 query=%s error=%s",
                    retrieval_query,
                    exc,
                )

            bm25_documents: list[Document] = []
            if self.bm25_retriever is not None:
                try:
                    bm25_documents = self.bm25_retriever.invoke(
                        retrieval_query
                    )[: config.RETRIEVE_CANDIDATES]
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "批量查询 BM25 召回失败 query=%s error=%s",
                        retrieval_query,
                        exc,
                    )

            if bm25_documents and vector_documents:
                result_sets.append(
                    reciprocal_rank_fusion(
                        [bm25_documents, vector_documents],
                        rrf_k=60,
                        weights=[config.BM25_WEIGHT, config.VECTOR_WEIGHT],
                        limit=config.RETRIEVE_CANDIDATES,
                    )
                )
            else:
                result_sets.append(
                    (bm25_documents or vector_documents)[
                        : config.RETRIEVE_CANDIDATES
                    ]
                )
        return result_sets

    def add_text(self, text: str, metadata: Dict | None = None):
        """把一段文本写入知识库。

        步骤：结构分析 -> 分块 -> 创建 Document -> 写入 Chroma。
        返回写入的分块数量。
        """
        docs = ingestion_service.split_text(text, metadata or {})
        return self.add_documents(docs)

    def add_documents(self, documents: List[Document]):
        """把已经分好块的 Document 直接写入向量库。

        结构化摄取流程已经完成分块；metadata 会保留来源和章节信息。
        注意：这里不再重复分块，调用方负责完成解析与分块。
        返回写入向量库的 ID 列表，调用方可回填到 chunk.vector_id。
        """
        ids = self.vectorstore.add_documents(documents)
        # 不同版本的 Chroma 持久化方式略有差异，做一次兼容处理。
        if hasattr(self.vectorstore, "persist"):
            self.vectorstore.persist()
        # 新文档入库后重建 BM25 内存索引，否则关键词检索看不到新内容。
        self.refresh_retriever()
        return ids

    def knowledge_count(self) -> int:
        """返回知识库当前的分块总数，供健康检查或前端展示。"""
        return len(self.vectorstore.get()["ids"])

    @staticmethod
    def _build_prompt_input(data: dict) -> dict:
        """把检索结果整理成 Prompt 模板需要的输入。"""
        docs = data["docs"]
        return {
            "context": build_evidence_context(docs),
            "question": data["question"],
            "history": data["history"],
            "retrieval_query": data.get("retrieval_query", data["question"]),
        }

    def _prepare_chat(
        self,
        question: str,
        history: List[dict],
        request_id: str | None = None,
    ) -> dict:
        """普通/流式问答共用的预处理：检索片段、整理来源与 Prompt 输入。"""
        trace = RagTrace(request_id)
        timings: dict[str, float] = {}
        timing_token = _TIMING_CONTEXT.set(timings)
        try:
            rewrite_started = time.perf_counter()
            rewrite = self.query_rewriter.rewrite(question, history)
            timings["query_rewrite_ms"] = round(
                (time.perf_counter() - rewrite_started) * 1000,
                2,
            )
            query_plan = (
                query_planner.plan(question, rewrite, history)
                if config.QUERY_PLANNER_ENABLED
                else QueryPlan(
                    original_question=question,
                    retrieval_queries=[rewrite["query"]],
                    subquestions=[rewrite["query"]],
                )
            )
            retrieval_queries = list(query_plan.retrieval_queries or [rewrite["query"]])
            if not config.MULTI_QUERY_ENABLED:
                retrieval_queries = retrieval_queries[:1]
            else:
                retrieval_queries = retrieval_queries[
                    : max(1, config.MULTI_QUERY_MAX_QUERIES)
                ]
            if not retrieval_queries:
                retrieval_queries = [rewrite["query"]]
            retrieval_question = retrieval_queries[0]
            trace.record_value("query_plan", query_plan.to_dict())
            trace.record_value("retrieval_query", retrieval_question)
            trace.record_value("retrieval_queries", retrieval_queries)
            if retrieval_question != question:
                logging.getLogger(__name__).info(
                    "query_rewrite original=%s rewritten=%s slots=%s",
                    question,
                    retrieval_question,
                    rewrite.get("slots", {}),
                )

            if config.QUERY_CLARIFICATION_ENABLED and query_plan.needs_clarification:
                clarification = query_plan.clarification_question or (
                    "请补充具体事项或文件名称，我再按对应条款回答。"
                )
                timings["clarification_ms"] = 0.0
                timings["prompt_build_ms"] = 0.0
                coverage = answer_validator.build_coverage(query_plan.subquestions, [])
                timings["subquestion_count"] = float(coverage["subquestion_count"])
                timings["subquestion_covered_count"] = float(coverage["covered_count"])
                trace.record_stage(
                    "clarification",
                    [],
                    extra={"question": clarification, "reason": query_plan.clarification_reason},
                )
                trace.record_value("coverage", coverage)
                trace.save()
                return {
                    "docs": [],
                    "sources": [],
                    "timings": timings,
                    "rewrite": rewrite,
                    "query_plan": query_plan.to_dict(),
                    "coverage": coverage,
                    "clarification": clarification,
                    "input_data": {
                        "docs": [],
                        "question": question,
                        "history": "",
                        "retrieval_query": retrieval_question,
                    },
                }

            scope_started = time.perf_counter()
            retrieval_scope = self._resolve_retrieval_scope(query_plan.to_dict())
            timings["retrieval_scope_ms"] = round(
                (time.perf_counter() - scope_started) * 1000,
                2,
            )
            timings["retrieval_source_scope_count"] = float(
                len(retrieval_scope.allowed_source_ids)
            )
            applicability_notice = self._build_applicability_notice(
                retrieval_scope
            )
            timings["applicability_fallback"] = (
                1.0 if retrieval_scope.applicability_mode == "fallback" else 0.0
            )
            trace.record_value("retrieval_scope", retrieval_scope.to_trace_dict())
            if retrieval_scope.applicability_mode == "none":
                clarification = (
                    applicability_notice
                    or "当前知识库没有找到可用于回答该问题的文件。"
                )
                coverage = answer_validator.build_coverage(query_plan.subquestions, [])
                trace.record_stage(
                    "applicability_failure",
                    [],
                    extra={"reason": "no_applicable_document"},
                )
                trace.record_value("coverage", coverage)
                trace.save()
                timings["subquestion_count"] = float(coverage["subquestion_count"])
                timings["subquestion_covered_count"] = float(coverage["covered_count"])
                return {
                    "docs": [],
                    "sources": [],
                    "timings": timings,
                    "rewrite": rewrite,
                    "query_plan": query_plan.to_dict(),
                    "retrieval_scope": retrieval_scope.to_trace_dict(),
                    "applicability_notice": applicability_notice,
                    "coverage": coverage,
                    "clarification": clarification,
                    "input_data": {
                        "docs": [],
                        "question": question,
                        "history": "",
                        "retrieval_query": retrieval_question,
                    },
                }

            # 混合检索先召回较多候选，再由 Rerank 精排，最后取 TOP_K 条给 LLM。
            retrieval_started = time.perf_counter()
            def retrieve_one(retrieval_query: str) -> list[Document]:
                try:
                    return self.retriever.invoke(retrieval_query)[
                        : config.RETRIEVE_CANDIDATES
                    ]
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "查询召回失败 query=%s error=%s",
                        retrieval_query,
                        exc,
                    )
                    return []

            batch_used = False
            if (
                len(retrieval_queries) > 1
                and config.EMBEDDING_QUERY_BATCH_ENABLED
            ):
                try:
                    result_sets = self._retrieve_multi_query_batched(
                        retrieval_queries
                    )
                    batch_used = bool(result_sets)
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "批量查询 Embedding 失败，回退逐 Query 召回: %s",
                        exc,
                    )

            if not batch_used:
                if len(retrieval_queries) > 1:
                    worker_count = max(
                        1,
                        min(
                            config.MULTI_QUERY_MAX_WORKERS,
                            len(retrieval_queries),
                        ),
                    )
                    with ThreadPoolExecutor(max_workers=worker_count) as executor:
                        result_sets = list(
                            executor.map(retrieve_one, retrieval_queries)
                        )
                else:
                    result_sets = [retrieve_one(retrieval_queries[0])]
            if len(result_sets) > 1:
                weights = [1.0] + [
                    config.MULTI_QUERY_SECONDARY_WEIGHT
                    for _ in result_sets[1:]
                ]
                raw_candidates = reciprocal_rank_fusion(
                    result_sets,
                    rrf_k=config.MULTI_QUERY_RRF_K,
                    weights=weights,
                    limit=config.RERANK_CANDIDATES,
                )
            else:
                raw_candidates = result_sets[0] if result_sets else []
            trace.record_stage("retrieval_raw", raw_candidates)
            candidates = raw_candidates[: config.RERANK_CANDIDATES]
            candidates = self._exclude_disabled_documents(
                candidates,
                scope=retrieval_scope,
            )
            trace.record_stage("retrieval_candidates", candidates)
            timings["retrieval_ms"] = round((time.perf_counter() - retrieval_started) * 1000, 2)
            timings["retrieval_candidates"] = float(len(candidates))
            timings["retrieval_query_count"] = float(len(retrieval_queries))
            timings["query_embedding_batch_used"] = 1.0 if batch_used else 0.0

            rerank_started = time.perf_counter()
            # 检索查询已经过消歧、规则归一并保留关键约束，Rerank 使用同一查询。
            rerank_query = retrieval_question
            reranked = reranker.rerank(rerank_query, candidates)
            reranked = boost_quoted_title_matches(reranked, question)
            trace.record_stage("reranked", reranked)
            docs = reranked[: config.TOP_K]
            timings["rerank_ms"] = round((time.perf_counter() - rerank_started) * 1000, 2)
            timings["reranked_count"] = float(len(docs))

            coverage_started = time.perf_counter()
            docs = self._fill_evidence_coverage(
                docs,
                query_plan,
                scope=retrieval_scope,
            )
            trace.record_stage("coverage_fill", docs)
            timings["evidence_coverage_fill_ms"] = round(
                (time.perf_counter() - coverage_started) * 1000,
                2,
            )

            # 父级扩展优先恢复完整条款、表格或记录组；相邻扩展只作为最后兜底。
            parent_started = time.perf_counter()
            docs = self._expand_parent_chunks(docs)
            trace.record_stage("parent_expansion", docs)
            timings["parent_expansion_ms"] = round(
                (time.perf_counter() - parent_started) * 1000,
                2,
            )
            timings["parent_expanded_count"] = float(len(docs))

            expansion_started = time.perf_counter()
            docs = self._expand_neighboring_chunks(docs)
            trace.record_stage("neighbor_expansion", docs)
            timings["neighbor_expansion_ms"] = round(
                (time.perf_counter() - expansion_started) * 1000,
                2,
            )
            timings["expanded_count"] = float(len(docs))

            docs = self._enrich_document_metadata(docs)
            docs = build_evidence_objects(docs)
            trace.record_stage("evidence_objects", docs)
            coverage = answer_validator.build_coverage(
                query_plan.subquestions,
                docs,
            )
            trace.record_context("final_context", docs)
            trace.record_value("coverage", coverage)
            trace.save()
            timings["subquestion_count"] = float(coverage["subquestion_count"])
            timings["subquestion_covered_count"] = float(coverage["covered_count"])

            prompt_started = time.perf_counter()
            sources = [{"content": doc.page_content, "metadata": doc.metadata} for doc in docs]
            # 只取最近 6 条历史，避免上下文过长；为空时展示“（无）”。
            history_text = "\n".join(
                f"{item['role']}: {item['content']}" for item in history[-6:]
            ) or "（无）"
            timings["prompt_build_ms"] = round(
                (time.perf_counter() - prompt_started) * 1000,
                2,
            )
        finally:
            _TIMING_CONTEXT.reset(timing_token)

        return {
            "docs": docs,
            "sources": sources,
            "timings": timings,
            "rewrite": rewrite,
            "query_plan": query_plan.to_dict(),
            "retrieval_scope": retrieval_scope.to_trace_dict(),
            "applicability_notice": applicability_notice,
            "coverage": coverage,
            "input_data": {
                "docs": docs,
                "question": question,
                "history": history_text,
                "retrieval_query": retrieval_question,
            },
        }

    @staticmethod
    def _build_applicability_notice(scope: RetrievalScope) -> str:
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

    def _exclude_disabled_documents(
        self,
        documents: List[Document],
        query_plan: dict | None = None,
        scope: RetrievalScope | None = None,
    ) -> List[Document]:
        if not documents:
            return documents
        scope = scope or self._resolve_retrieval_scope(query_plan or {})
        return [
            document
            for document in documents
            if document.metadata.get("source_file_id") in scope.allowed_source_ids
        ]

    def _resolve_retrieval_scope(
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
            active_ids = RagService._select_source_ids(
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
    def _enrich_document_metadata(documents: List[Document]) -> List[Document]:
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
            try:
                source_file_id = int(document.metadata.get("source_file_id"))
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

    def _fill_evidence_coverage(
        self,
        documents: List[Document],
        query_plan: QueryPlan,
        scope: RetrievalScope | None = None,
    ) -> List[Document]:
        if (
            not config.EVIDENCE_COVERAGE_ENABLED
            or self.bm25_retriever is None
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
        scope = scope or self._resolve_retrieval_scope(query_plan.to_dict())

        for subquestion in missing:
            try:
                candidates = self.bm25_retriever.invoke(subquestion)
            except Exception:
                continue
            candidates = self._exclude_disabled_documents(
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

    def _expand_parent_chunks(self, docs: List[Document]) -> List[Document]:
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
                result = self.vectorstore.get(
                    where=where,
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

    def _expand_neighboring_chunks(self, docs: List[Document]) -> List[Document]:
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
                result = self.vectorstore.get(
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

    def chat(
        self,
        question: str,
        history: List[dict],
        thread_id: str | None = None,
        history_trusted: bool = False,
    ):
        """非流式 RAG 问答，作为流式失败后的降级路径。

        返回 (回答文本, 来源列表, 运行模式, 阶段耗时, 请求 ID, 综合置信度)。
        """
        request_id = uuid.uuid4().hex[:12]
        total_started = time.perf_counter()
        memory_started = time.perf_counter()
        memory_context = self._load_memory_context(thread_id, history, history_trusted)
        memory_load_ms = round((time.perf_counter() - memory_started) * 1000, 2)
        prepared = self._prepare_chat(
            question,
            memory_context.messages,
            request_id=request_id,
        )
        timings = prepared["timings"]
        timings["memory_load_ms"] = memory_load_ms
        timings["memory_loaded_count"] = float(memory_context.loaded)
        applicability_notice = str(prepared.get("applicability_notice") or "")
        if prepared.get("clarification"):
            answer = prepared["clarification"]
            mode = "rag"
            timings["llm_generation_ms"] = 0.0
        elif self.chat_chain is None:
            answer = self._demo_answer(question, prepared["docs"])
            answer = applicability_notice + answer
            mode = "demo"
            timings["llm_generation_ms"] = 0.0
        else:
            llm_started = time.perf_counter()
            response = self.chat_chain.invoke(prepared["input_data"])
            answer = response.content
            mode = "rag"
            timings["llm_generation_ms"] = round((time.perf_counter() - llm_started) * 1000, 2)
            if answer_verifier.enabled:
                verification_started = time.perf_counter()
                answer, verification = answer_verifier.review_and_repair(
                    question=question,
                    answer=answer,
                    documents=prepared["docs"],
                    history=prepared["input_data"]["history"],
                )
                timings["answer_verification_ms"] = round(
                    (time.perf_counter() - verification_started) * 1000,
                    2,
                )
                timings["answer_repaired_count"] = float(verification.get("repaired", False))
            answer = applicability_notice + answer
            memory_answer = answer
            answer = append_source_footer(answer, prepared["docs"])

        if prepared.get("clarification"):
            confidence = self._clarification_confidence(prepared)
        else:
            confidence = confidence_evaluator.evaluate(
                question=question,
                answer=answer,
                documents=prepared["docs"],
                rewrite=prepared.get("rewrite"),
                retrieval_query=prepared["input_data"].get("retrieval_query"),
                coverage=prepared.get("coverage"),
                query_plan=prepared.get("query_plan"),
                applicability_scope=prepared.get("retrieval_scope"),
            )
        timings["total_ms"] = round((time.perf_counter() - total_started) * 1000, 2)
        self._save_memory_turn(
            memory_context.thread_id,
            question,
            memory_answer if "memory_answer" in locals() else answer,
            timings,
        )
        confidence_payload = (
            confidence.to_dict()
            if hasattr(confidence, "to_dict")
            else confidence
        )
        self._log_timings(request_id, mode, timings)
        self._log_confidence(request_id, confidence_payload)
        return answer, prepared["sources"], mode, timings, request_id, confidence_payload

    def stream_chat(
        self,
        question: str,
        history: List[dict],
        thread_id: str | None = None,
        history_trusted: bool = False,
    ):
        """流式 RAG 问答事件生成器。

        依次产出事件 dict：
        {"type": "token", "content": "..."}
        {"type": "error", "message": "..."}   （生成中途失败时）
        {"type": "sources", "sources": [...]}  （回答结束后）
        {"type": "timings", "timings": {...}, "request_id": "..."}
        """
        request_id = uuid.uuid4().hex[:12]
        total_started = time.perf_counter()
        memory_started = time.perf_counter()
        memory_context = self._load_memory_context(thread_id, history, history_trusted)
        memory_load_ms = round((time.perf_counter() - memory_started) * 1000, 2)
        prepared = self._prepare_chat(
            question,
            memory_context.messages,
            request_id=request_id,
        )
        timings = prepared["timings"]
        timings["memory_load_ms"] = memory_load_ms
        timings["memory_loaded_count"] = float(memory_context.loaded)
        applicability_notice = str(prepared.get("applicability_notice") or "")

        if prepared.get("clarification"):
            answer = prepared["clarification"]
            timings["llm_first_token_ms"] = 0.0
            timings["llm_generation_ms"] = 0.0
            timings["total_ms"] = round((time.perf_counter() - total_started) * 1000, 2)
            confidence = self._clarification_confidence(prepared)
            yield {"type": "token", "content": answer}
            yield {"type": "sources", "sources": []}
            self._save_memory_turn(memory_context.thread_id, question, answer, timings)
            yield {"type": "timings", "timings": timings, "request_id": request_id}
            yield {"type": "confidence", "confidence": confidence}
            self._log_timings(request_id, "clarification", timings)
            self._log_confidence(request_id, confidence)
            return

        # 演示模式：模拟逐段输出，便于前端无 Key 联调。
        if self.chat_chain is None:
            demo_text = self._demo_answer(question, prepared["docs"])
            demo_text = applicability_notice + demo_text
            demo_text = append_source_footer(demo_text, prepared["docs"])
            generation_started = time.perf_counter()
            first_token_ms = None
            for start in range(0, len(demo_text), 12):
                if first_token_ms is None:
                    first_token_ms = round((time.perf_counter() - generation_started) * 1000, 2)
                yield {"type": "token", "content": demo_text[start : start + 12]}
            timings["llm_first_token_ms"] = first_token_ms or 0.0
            timings["llm_generation_ms"] = round(
                (time.perf_counter() - generation_started) * 1000,
                2,
            )
            timings["total_ms"] = round((time.perf_counter() - total_started) * 1000, 2)
            confidence = confidence_evaluator.evaluate(
                question,
                demo_text,
                prepared["docs"],
                prepared.get("rewrite"),
                prepared["input_data"].get("retrieval_query"),
                coverage=prepared.get("coverage"),
                query_plan=prepared.get("query_plan"),
                applicability_scope=prepared.get("retrieval_scope"),
            )
            yield {"type": "sources", "sources": prepared["sources"]}
            self._save_memory_turn(memory_context.thread_id, question, demo_text, timings)
            yield {"type": "timings", "timings": timings, "request_id": request_id}
            yield {"type": "confidence", "confidence": confidence.to_dict()}
            self._log_timings(request_id, "demo", timings)
            self._log_confidence(request_id, confidence.to_dict())
            return

        generation_started = time.perf_counter()
        yield {"type": "status", "message": "generating"}
        if applicability_notice:
            yield {"type": "token", "content": applicability_notice}
        first_token_ms = None
        answer_chunks: list[str] = []
        try:
            for chunk in self.chat_chain.stream(prepared["input_data"]):
                content = getattr(chunk, "content", None) or ""
                if content:
                    answer_chunks.append(content)
                    if first_token_ms is None:
                        first_token_ms = round((time.perf_counter() - generation_started) * 1000, 2)
                    yield {"type": "token", "content": content}
        except Exception as exc:
            # 前端收到 error 事件后会清空已渲染内容并调用普通接口兜底。
            timings["llm_generation_ms"] = round(
                (time.perf_counter() - generation_started) * 1000,
                2,
            )
            timings["total_ms"] = round((time.perf_counter() - total_started) * 1000, 2)
            self._log_timings(request_id, "stream_error", timings)
            yield {"type": "error", "message": str(exc)}
            return

        timings["llm_first_token_ms"] = first_token_ms or 0.0
        timings["llm_generation_ms"] = round((time.perf_counter() - generation_started) * 1000, 2)
        answer = "".join(answer_chunks)
        repaired = False
        if answer_verifier.enabled:
            verification_started = time.perf_counter()
            verified_answer, verification = answer_verifier.review_and_repair(
                question=question,
                answer=answer,
                documents=prepared["docs"],
                history=prepared["input_data"]["history"],
            )
            timings["answer_verification_ms"] = round(
                (time.perf_counter() - verification_started) * 1000,
                2,
            )
            repaired = bool(verification.get("repaired"))
            timings["answer_repaired_count"] = float(repaired)
            if repaired:
                answer = verified_answer
        timings["total_ms"] = round((time.perf_counter() - total_started) * 1000, 2)
        display_answer = applicability_notice + answer
        final_answer = append_source_footer(display_answer, prepared["docs"])
        if repaired:
            yield {"type": "replace", "content": final_answer}
        source_footer = ""
        if not repaired:
            source_footer = build_new_source_footer(
                "".join(answer_chunks),
                prepared["docs"],
            )
        confidence = confidence_evaluator.evaluate(
            question,
            answer,
            prepared["docs"],
            prepared.get("rewrite"),
            prepared["input_data"].get("retrieval_query"),
            coverage=prepared.get("coverage"),
            query_plan=prepared.get("query_plan"),
            applicability_scope=prepared.get("retrieval_scope"),
        )
        if source_footer:
            yield {"type": "token", "content": source_footer}
        self._save_memory_turn(memory_context.thread_id, question, display_answer, timings)
        yield {"type": "sources", "sources": prepared["sources"]}
        yield {"type": "timings", "timings": timings, "request_id": request_id}
        yield {"type": "confidence", "confidence": confidence.to_dict()}
        self._log_timings(request_id, "stream", timings)
        self._log_confidence(request_id, confidence.to_dict())

    @staticmethod
    def _clarification_confidence(prepared: dict) -> dict:
        """构造澄清响应的确定性置信度结果。"""
        query_plan = prepared.get("query_plan") or {}
        reason = str(query_plan.get("clarification_reason") or "需要补充查询信息")
        return {
            "overall": 0.0,
            "retrieval_confidence": 0.0,
            "generation_confidence": 0.0,
            "risk_penalty": 0.0,
            "action": "clarify",
            "signals": {"clarification_risk": 0.25},
            "reasons": [reason],
        }

    @staticmethod
    def _save_memory_turn(
        thread_id: str | None,
        question: str,
        answer: str,
        timings: dict[str, float],
    ) -> None:
        started = time.perf_counter()
        try:
            short_term_memory.record_turn(thread_id, question, answer)
            timings["memory_error_count"] = 0.0
        except Exception as exc:
            timings["memory_error_count"] = 1.0
            logging.getLogger(__name__).warning("短期记忆写入失败: %s", exc)
        timings["memory_save_ms"] = round((time.perf_counter() - started) * 1000, 2)

    @staticmethod
    def _load_memory_context(
        thread_id: str | None,
        history: List[dict],
        history_trusted: bool,
    ) -> MemoryContext:
        try:
            return short_term_memory.prepare_context(
                thread_id,
                history,
                trusted_history=history_trusted,
            )
        except Exception as exc:
            logging.getLogger(__name__).warning("短期记忆读取失败: %s", exc)
            return MemoryContext(
                None,
                history[-config.SHORT_TERM_CONTEXT_MESSAGES :],
                False,
            )

    @staticmethod
    def _log_timings(request_id: str, mode: str, timings: dict[str, float]) -> None:
        """输出阶段耗时日志，便于后续统计 P50/P95。"""
        payload = " ".join(
            f"{key}={int(value)}" if key.endswith("_count") else f"{key}={value:.2f}ms"
            for key, value in timings.items()
        )
        logging.getLogger(__name__).info(
            "chat_timings request_id=%s mode=%s %s",
            request_id,
            mode,
            payload,
        )

    @staticmethod
    def _log_confidence(request_id: str, confidence: dict) -> None:
        """输出置信度总分、动作和主要信号。"""
        signals = confidence.get("signals", {})
        signal_text = " ".join(
            f"{key}={float(value):.4f}"
            for key, value in signals.items()
        )
        logging.getLogger(__name__).info(
            "answer_confidence request_id=%s overall=%.4f retrieval=%.4f generation=%.4f "
            "risk=%.4f action=%s %s reasons=%s",
            request_id,
            float(confidence.get("overall", 0)),
            float(confidence.get("retrieval_confidence", 0)),
            float(confidence.get("generation_confidence", 0)),
            float(confidence.get("risk_penalty", 0)),
            confidence.get("action", ""),
            signal_text,
            "；".join(confidence.get("reasons", [])),
        )
    @staticmethod
    def _demo_answer(question: str, docs: List) -> str:
        """演示模式的本地回答：展示检索到的内容，让无 Key 时也能跑通链路。"""
        if not docs:
            return (
                f"已收到问题：「{question}」。\n\n"
                "当前为演示模式，知识库中还没有可用资料。配置 API Key 后可启用真实 RAG 回答，"
                "或先通过 /api/upload 上传资料。"
            )
        excerpt = docs[0].page_content.strip().replace("\n", " ")
        return (
            f"已收到问题：「{question}」。\n\n"
            "当前为演示模式，我根据知识库检索到以下相关资料：\n\n"
            f"{excerpt[:200]}"
        )


# 模块级单例：FastAPI 启动时只初始化一次向量库与模型客户端。
rag_service = RagService()
