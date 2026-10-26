"""RAG 查询规划、召回、Rerank 与证据准备流程。"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, List

from langchain_core.documents import Document

from .. import config
from ..answer_validator import answer_validator
from ..citations import build_evidence_context
from ..evidence_objects import build_evidence_objects
from ..evidence_selector import boost_quoted_title_matches
from ..query_planner import QueryPlan, query_planner
from ..query_rewriter import QueryRewriter
from ..rag_trace import RagTrace
from ..reranker import reranker
from ..retrieval_fusion import reciprocal_rank_fusion
from ..retrieval_scope import RetrievalScope
from .cancellation import StreamCancelled, raise_if_cancelled
from .contracts import PreparedChat
from .evidence import RagEvidence
from .observability import record_timing, reset_timing_context, set_timing_context
from .runtime import RagRuntime


@dataclass(slots=True)
class _PreparedQuery:
    rewrite: dict[str, Any]
    plan: QueryPlan
    retrieval_queries: list[str]
    retrieval_question: str


@dataclass(slots=True)
class _PreparedScope:
    scope: RetrievalScope
    applicability_notice: str


class RagRetrieval:
    """查询改写、召回、Rerank、版本范围和证据组织。"""

    def __init__(
        self,
        runtime: RagRuntime,
        evidence: RagEvidence,
    ) -> None:
        self.runtime = runtime
        self.evidence = evidence
        self.query_rewriter = QueryRewriter()

    def _retrieve_multi_query_batched(
        self,
        retrieval_queries: list[str],
    ) -> list[list[Document]]:
        """批量计算查询向量，再分别执行混合召回。"""
        embedding_started = time.perf_counter()
        query_vectors = self.runtime.embeddings.embed_documents(retrieval_queries)
        record_timing("query_embedding_batch_ms", embedding_started)
        if len(query_vectors) != len(retrieval_queries):
            raise ValueError("query embedding count does not match query count")

        result_sets: list[list[Document]] = []
        for retrieval_query, query_vector in zip(retrieval_queries, query_vectors):
            vector_documents: list[Document] = []
            try:
                vector_documents = self.runtime.vectorstore.similarity_search_by_vector(
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
            if self.runtime.bm25_retriever is not None:
                try:
                    bm25_documents = self.runtime.bm25_retriever.invoke(
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

    @staticmethod
    def build_prompt_input(data: dict) -> dict:
        """把检索结果整理成 Prompt 模板需要的输入。"""
        docs = data["docs"]
        return {
            "context": build_evidence_context(docs),
            "question": data["question"],
            "history": data["history"],
            "retrieval_query": data.get("retrieval_query", data["question"]),
        }

    def prepare_chat(
        self,
        question: str,
        history: List[dict],
        request_id: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> PreparedChat:
        """执行问答生成前的全部检索与证据准备阶段。"""
        trace = RagTrace(request_id)
        timings: dict[str, float] = {}
        timing_token = set_timing_context(timings)
        try:
            raise_if_cancelled(cancel_event, "prepare_start", request_id)
            query = self._prepare_query(
                question,
                history,
                timings,
                trace,
                request_id,
                cancel_event,
            )

            if config.QUERY_CLARIFICATION_ENABLED and query.plan.needs_clarification:
                raise_if_cancelled(
                    cancel_event,
                    "before_clarification",
                    request_id,
                )
                clarification = query.plan.clarification_question or (
                    "请补充具体事项或文件名称，我再按对应条款回答。"
                )
                timings["clarification_ms"] = 0.0
                timings["prompt_build_ms"] = 0.0
                coverage = answer_validator.build_coverage(
                    query.plan.subquestions,
                    [],
                )
                return self._build_clarification(
                    question=question,
                    query=query,
                    timings=timings,
                    coverage=coverage,
                    clarification=clarification,
                    trace=trace,
                    stage="clarification",
                    extra={
                        "question": clarification,
                        "reason": query.plan.clarification_reason,
                    },
                )

            prepared_scope = self._prepare_scope(query.plan, timings, trace)
            if prepared_scope.scope.applicability_mode == "none":
                clarification = (
                    prepared_scope.applicability_notice
                    or "当前知识库没有找到可用于回答该问题的文件。"
                )
                coverage = answer_validator.build_coverage(
                    query.plan.subquestions,
                    [],
                )
                return self._build_clarification(
                    question=question,
                    query=query,
                    timings=timings,
                    coverage=coverage,
                    clarification=clarification,
                    trace=trace,
                    stage="applicability_failure",
                    extra={"reason": "no_applicable_document"},
                    prepared_scope=prepared_scope,
                )

            candidates, batch_used = self._recall_candidates(
                query,
                prepared_scope.scope,
                timings,
                trace,
                request_id,
                cancel_event,
            )
            docs = self._rerank_candidates(
                question,
                query,
                candidates,
                timings,
                trace,
                request_id,
                cancel_event,
            )
            docs, coverage = self._build_evidence(
                docs,
                query.plan,
                prepared_scope.scope,
                timings,
                trace,
                request_id,
                cancel_event,
            )
            sources, history_text = self._build_prompt_payload(
                docs,
                history,
                timings,
                request_id,
                cancel_event,
            )
            timings["query_embedding_batch_used"] = 1.0 if batch_used else 0.0
            return PreparedChat(
                docs=docs,
                sources=sources,
                timings=timings,
                rewrite=query.rewrite,
                query_plan=query.plan.to_dict(),
                retrieval_scope=prepared_scope.scope.to_trace_dict(),
                applicability_notice=prepared_scope.applicability_notice,
                coverage=coverage,
                input_data={
                    "docs": docs,
                    "question": question,
                    "history": history_text,
                    "retrieval_query": query.retrieval_question,
                },
            )
        finally:
            reset_timing_context(timing_token)

    def _prepare_query(
        self,
        question: str,
        history: List[dict],
        timings: dict[str, float],
        trace: RagTrace,
        request_id: str | None,
        cancel_event: threading.Event | None,
    ) -> _PreparedQuery:
        rewrite_started = time.perf_counter()
        rewrite = self.query_rewriter.rewrite(question, history)
        timings["query_rewrite_ms"] = round(
            (time.perf_counter() - rewrite_started) * 1000,
            2,
        )
        raise_if_cancelled(cancel_event, "after_rewrite", request_id)
        query_plan = (
            query_planner.plan(question, rewrite, history)
            if config.QUERY_PLANNER_ENABLED
            else QueryPlan(
                original_question=question,
                retrieval_queries=[rewrite["query"]],
                subquestions=[rewrite["query"]],
            )
        )
        raise_if_cancelled(cancel_event, "after_query_plan", request_id)

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
        return _PreparedQuery(
            rewrite=rewrite,
            plan=query_plan,
            retrieval_queries=retrieval_queries,
            retrieval_question=retrieval_question,
        )

    def _prepare_scope(
        self,
        query_plan: QueryPlan,
        timings: dict[str, float],
        trace: RagTrace,
    ) -> _PreparedScope:
        scope_started = time.perf_counter()
        retrieval_scope = self.evidence.resolve_retrieval_scope(query_plan.to_dict())
        timings["retrieval_scope_ms"] = round(
            (time.perf_counter() - scope_started) * 1000,
            2,
        )
        timings["retrieval_source_scope_count"] = float(
            len(retrieval_scope.allowed_source_ids)
        )
        applicability_notice = self.evidence.build_applicability_notice(
            retrieval_scope
        )
        timings["applicability_fallback"] = (
            1.0 if retrieval_scope.applicability_mode == "fallback" else 0.0
        )
        trace.record_value("retrieval_scope", retrieval_scope.to_trace_dict())
        return _PreparedScope(
            scope=retrieval_scope,
            applicability_notice=applicability_notice,
        )

    def _recall_candidates(
        self,
        query: _PreparedQuery,
        retrieval_scope: RetrievalScope,
        timings: dict[str, float],
        trace: RagTrace,
        request_id: str | None,
        cancel_event: threading.Event | None,
    ) -> tuple[list[Document], bool]:
        raise_if_cancelled(cancel_event, "before_retrieval", request_id)
        retrieval_started = time.perf_counter()

        def retrieve_one(retrieval_query: str) -> list[Document]:
            raise_if_cancelled(cancel_event, "retrieval_worker", request_id)
            try:
                return self.runtime.retriever.invoke(retrieval_query)[
                    : config.RETRIEVE_CANDIDATES
                ]
            except StreamCancelled:
                raise
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "查询召回失败 query=%s error=%s",
                    retrieval_query,
                    exc,
                )
                return []

        result_sets: list[list[Document]] = []
        batch_used = False
        if (
            len(query.retrieval_queries) > 1
            and config.EMBEDDING_QUERY_BATCH_ENABLED
        ):
            try:
                result_sets = self._retrieve_multi_query_batched(
                    query.retrieval_queries
                )
                batch_used = bool(result_sets)
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "批量查询 Embedding 失败，回退逐 Query 召回: %s",
                    exc,
                )

        if not batch_used:
            if len(query.retrieval_queries) > 1:
                worker_count = max(
                    1,
                    min(
                        config.MULTI_QUERY_MAX_WORKERS,
                        len(query.retrieval_queries),
                    ),
                )
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    result_sets = list(
                        executor.map(retrieve_one, query.retrieval_queries)
                    )
            else:
                result_sets = [retrieve_one(query.retrieval_queries[0])]

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

        raise_if_cancelled(cancel_event, "after_retrieval", request_id)
        trace.record_stage("retrieval_raw", raw_candidates)
        candidates = raw_candidates[: config.RERANK_CANDIDATES]
        candidates = self.evidence.exclude_disabled_documents(
            candidates,
            scope=retrieval_scope,
        )
        trace.record_stage("retrieval_candidates", candidates)
        timings["retrieval_ms"] = round(
            (time.perf_counter() - retrieval_started) * 1000,
            2,
        )
        timings["retrieval_candidates"] = float(len(candidates))
        timings["retrieval_query_count"] = float(len(query.retrieval_queries))
        return candidates, batch_used

    def _rerank_candidates(
        self,
        question: str,
        query: _PreparedQuery,
        candidates: list[Document],
        timings: dict[str, float],
        trace: RagTrace,
        request_id: str | None,
        cancel_event: threading.Event | None,
    ) -> list[Document]:
        raise_if_cancelled(cancel_event, "before_rerank", request_id)
        rerank_started = time.perf_counter()
        reranked = reranker.rerank(query.retrieval_question, candidates)
        reranked = boost_quoted_title_matches(reranked, question)
        trace.record_stage("reranked", reranked)
        docs = reranked[: config.TOP_K]
        timings["rerank_ms"] = round(
            (time.perf_counter() - rerank_started) * 1000,
            2,
        )
        timings["reranked_count"] = float(len(docs))
        raise_if_cancelled(cancel_event, "after_rerank", request_id)
        return docs

    def _build_evidence(
        self,
        docs: list[Document],
        query_plan: QueryPlan,
        retrieval_scope: RetrievalScope,
        timings: dict[str, float],
        trace: RagTrace,
        request_id: str | None,
        cancel_event: threading.Event | None,
    ) -> tuple[list[Document], dict[str, Any]]:
        raise_if_cancelled(cancel_event, "before_coverage_expansion", request_id)
        coverage_started = time.perf_counter()
        docs = self.evidence.fill_evidence_coverage(
            docs,
            query_plan,
            scope=retrieval_scope,
        )
        trace.record_stage("coverage_fill", docs)
        timings["evidence_coverage_fill_ms"] = round(
            (time.perf_counter() - coverage_started) * 1000,
            2,
        )

        raise_if_cancelled(cancel_event, "before_parent_expansion", request_id)
        parent_started = time.perf_counter()
        docs = self.evidence.expand_parent_chunks(docs)
        trace.record_stage("parent_expansion", docs)
        timings["parent_expansion_ms"] = round(
            (time.perf_counter() - parent_started) * 1000,
            2,
        )
        timings["parent_expanded_count"] = float(len(docs))

        expansion_started = time.perf_counter()
        docs = self.evidence.expand_neighboring_chunks(docs)
        trace.record_stage("neighbor_expansion", docs)
        timings["neighbor_expansion_ms"] = round(
            (time.perf_counter() - expansion_started) * 1000,
            2,
        )
        timings["expanded_count"] = float(len(docs))

        raise_if_cancelled(cancel_event, "before_evidence_build", request_id)
        docs = self.evidence.enrich_document_metadata(docs)
        docs = build_evidence_objects(docs)
        trace.record_stage("evidence_objects", docs)
        coverage = answer_validator.build_coverage(query_plan.subquestions, docs)
        trace.record_context("final_context", docs)
        trace.record_value("coverage", coverage)
        trace.save()
        timings["subquestion_count"] = float(coverage["subquestion_count"])
        timings["subquestion_covered_count"] = float(coverage["covered_count"])
        return docs, coverage

    def _build_prompt_payload(
        self,
        docs: list[Document],
        history: List[dict],
        timings: dict[str, float],
        request_id: str | None,
        cancel_event: threading.Event | None,
    ) -> tuple[list[dict[str, Any]], str]:
        raise_if_cancelled(cancel_event, "before_prompt_build", request_id)
        prompt_started = time.perf_counter()
        sources = [
            {"content": doc.page_content, "metadata": doc.metadata}
            for doc in docs
        ]
        history_text = "\n".join(
            f"{item['role']}: {item['content']}" for item in history[-6:]
        ) or "（无）"
        timings["prompt_build_ms"] = round(
            (time.perf_counter() - prompt_started) * 1000,
            2,
        )
        return sources, history_text

    def _build_clarification(
        self,
        *,
        question: str,
        query: _PreparedQuery,
        timings: dict[str, float],
        coverage: dict[str, Any],
        clarification: str,
        trace: RagTrace,
        stage: str,
        extra: dict[str, Any],
        prepared_scope: _PreparedScope | None = None,
    ) -> PreparedChat:
        trace.record_stage(stage, [], extra=extra)
        trace.record_value("coverage", coverage)
        trace.save()
        timings["subquestion_count"] = float(coverage["subquestion_count"])
        timings["subquestion_covered_count"] = float(coverage["covered_count"])
        retrieval_scope = (
            prepared_scope.scope.to_trace_dict()
            if prepared_scope is not None
            else {}
        )
        applicability_notice = (
            prepared_scope.applicability_notice
            if prepared_scope is not None
            else ""
        )
        return PreparedChat(
            docs=[],
            sources=[],
            timings=timings,
            rewrite=query.rewrite,
            query_plan=query.plan.to_dict(),
            retrieval_scope=retrieval_scope,
            applicability_notice=applicability_notice,
            coverage=coverage,
            clarification=clarification,
            input_data={
                "docs": [],
                "question": question,
                "history": "",
                "retrieval_query": query.retrieval_question,
            },
        )
