"""RAG 问答编排：普通生成、流式生成、记忆与后处理。"""

import logging
import threading
import time
import uuid
from typing import Any, List, cast

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from .. import config
from ..answer_verifier import answer_verifier
from ..citations import append_source_footer, build_new_source_footer
from ..confidence import ConfidenceResult, confidence_evaluator
from ..prompts import RAG_SYSTEM_PROMPT
from ..short_term_memory import MemoryContext, short_term_memory
from .cancellation import StreamCancelled, raise_if_cancelled
from .contracts import PreparedChat
from .retrieval import RagRetrieval
from .runtime import RagRuntime


class RagPipeline:
    """把检索结果转换为普通答案或 SSE 事件。"""

    def __init__(self, runtime: RagRuntime, retrieval: RagRetrieval) -> None:
        self.runtime = runtime
        self.retrieval = retrieval
        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", RAG_SYSTEM_PROMPT),
                ("human", "对话历史：{history}"),
                ("human", "结合历史后的检索意图：{retrieval_query}"),
                ("human", "用户问题：{question}"),
            ]
        )
        self.chat_chain = None
        if self.runtime.llm is not None:
            self.chat_chain = (
                RunnableLambda(self.retrieval.build_prompt_input)
                | self.prompt_template
                | self.runtime.llm
            )

    def chat(
        self,
        question: str,
        history: List[dict],
        thread_id: str | None = None,
        history_trusted: bool = False,
    ) -> tuple[str, list[dict], str, dict[str, float], str, dict[str, Any]]:
        """执行一次非流式 RAG 问答。"""
        request_id = uuid.uuid4().hex[:12]
        total_started = time.perf_counter()
        memory_started = time.perf_counter()
        memory_context = self._load_memory_context(thread_id, history, history_trusted)
        memory_load_ms = round((time.perf_counter() - memory_started) * 1000, 2)
        prepared = self.retrieval.prepare_chat(
            question,
            memory_context.messages,
            request_id=request_id,
        )
        timings = prepared.timings
        timings["memory_load_ms"] = memory_load_ms
        timings["memory_loaded_count"] = float(memory_context.loaded)
        applicability_notice = prepared.applicability_notice
        memory_answer: str | None = None
        if prepared.clarification:
            answer = prepared.clarification
            mode = "rag"
            timings["llm_generation_ms"] = 0.0
        elif self.chat_chain is None:
            answer = self._demo_answer(question, prepared.docs)
            answer = applicability_notice + answer
            mode = "demo"
            timings["llm_generation_ms"] = 0.0
        else:
            llm_started = time.perf_counter()
            response = self.chat_chain.invoke(prepared.input_data)
            answer = cast(str, response.content)
            mode = "rag"
            timings["llm_generation_ms"] = round(
                (time.perf_counter() - llm_started) * 1000,
                2,
            )
            if answer_verifier.enabled:
                verification_started = time.perf_counter()
                answer, verification = answer_verifier.review_and_repair(
                    question=question,
                    answer=answer,
                    documents=prepared.docs,
                    history=prepared.input_data["history"],
                )
                timings["answer_verification_ms"] = round(
                    (time.perf_counter() - verification_started) * 1000,
                    2,
                )
                timings["answer_repaired_count"] = float(
                    verification.get("repaired", False)
                )
            answer = applicability_notice + answer
            memory_answer = answer
            answer = append_source_footer(answer, prepared.docs)

        confidence: ConfidenceResult | dict[str, Any]
        if prepared.clarification:
            confidence = self._clarification_confidence(prepared)
        else:
            confidence = confidence_evaluator.evaluate(
                question=question,
                answer=answer,
                documents=prepared.docs,
                rewrite=prepared.rewrite,
                retrieval_query=prepared.input_data.get("retrieval_query"),
                coverage=prepared.coverage,
                query_plan=prepared.query_plan,
                applicability_scope=prepared.retrieval_scope,
            )
        timings["total_ms"] = round((time.perf_counter() - total_started) * 1000, 2)
        self._save_memory_turn(
            memory_context.thread_id,
            question,
            memory_answer if memory_answer is not None else answer,
            timings,
        )
        confidence_payload = self._confidence_payload(confidence)
        self._log_timings(request_id, mode, timings)
        self._log_confidence(request_id, confidence_payload)
        return answer, prepared.sources, mode, timings, request_id, confidence_payload

    def stream_chat(
        self,
        question: str,
        history: List[dict],
        thread_id: str | None = None,
        history_trusted: bool = False,
        cancel_event: threading.Event | None = None,
    ):
        """执行一次流式 RAG 问答并产出 SSE 事件。"""
        request_id = uuid.uuid4().hex[:12]
        raise_if_cancelled(cancel_event, "stream_start", request_id)
        total_started = time.perf_counter()
        memory_started = time.perf_counter()
        memory_context = self._load_memory_context(thread_id, history, history_trusted)
        memory_load_ms = round((time.perf_counter() - memory_started) * 1000, 2)
        raise_if_cancelled(cancel_event, "after_memory_load", request_id)
        prepared = self.retrieval.prepare_chat(
            question,
            memory_context.messages,
            request_id=request_id,
            cancel_event=cancel_event,
        )
        timings = prepared.timings
        timings["memory_load_ms"] = memory_load_ms
        timings["memory_loaded_count"] = float(memory_context.loaded)
        applicability_notice = prepared.applicability_notice

        if prepared.clarification:
            raise_if_cancelled(cancel_event, "before_clarification_yield", request_id)
            answer = prepared.clarification
            timings["llm_first_token_ms"] = 0.0
            timings["llm_generation_ms"] = 0.0
            timings["total_ms"] = round(
                (time.perf_counter() - total_started) * 1000,
                2,
            )
            confidence = self._clarification_confidence(prepared)
            yield {"type": "token", "content": answer}
            yield {"type": "sources", "sources": []}
            raise_if_cancelled(
                cancel_event,
                "before_clarification_memory_save",
                request_id,
            )
            self._save_memory_turn(
                memory_context.thread_id,
                question,
                answer,
                timings,
            )
            yield {"type": "timings", "timings": timings, "request_id": request_id}
            yield {"type": "confidence", "confidence": confidence}
            self._log_timings(request_id, "clarification", timings)
            self._log_confidence(request_id, confidence)
            return

        if self.chat_chain is None:
            raise_if_cancelled(cancel_event, "before_demo_generation", request_id)
            demo_text = self._demo_answer(question, prepared.docs)
            demo_text = applicability_notice + demo_text
            demo_text = append_source_footer(demo_text, prepared.docs)
            generation_started = time.perf_counter()
            first_token_ms = None
            for start in range(0, len(demo_text), 12):
                raise_if_cancelled(cancel_event, "demo_token_loop", request_id)
                if first_token_ms is None:
                    first_token_ms = round(
                        (time.perf_counter() - generation_started) * 1000,
                        2,
                    )
                yield {"type": "token", "content": demo_text[start : start + 12]}
            timings["llm_first_token_ms"] = first_token_ms or 0.0
            timings["llm_generation_ms"] = round(
                (time.perf_counter() - generation_started) * 1000,
                2,
            )
            timings["total_ms"] = round(
                (time.perf_counter() - total_started) * 1000,
                2,
            )
            confidence = confidence_evaluator.evaluate(
                question,
                demo_text,
                prepared.docs,
                prepared.rewrite,
                prepared.input_data.get("retrieval_query"),
                coverage=prepared.coverage,
                query_plan=prepared.query_plan,
                applicability_scope=prepared.retrieval_scope,
            )
            yield {"type": "sources", "sources": prepared.sources}
            raise_if_cancelled(cancel_event, "before_demo_memory_save", request_id)
            self._save_memory_turn(
                memory_context.thread_id,
                question,
                demo_text,
                timings,
            )
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
        llm_stream = None
        try:
            raise_if_cancelled(cancel_event, "before_llm_stream", request_id)
            llm_stream = self.chat_chain.stream(prepared.input_data)
            llm_iterator = iter(llm_stream)
            while True:
                raise_if_cancelled(cancel_event, "llm_token_loop", request_id)
                try:
                    chunk = next(llm_iterator)
                except StopIteration:
                    break
                content = getattr(chunk, "content", None) or ""
                if content:
                    answer_chunks.append(content)
                    if first_token_ms is None:
                        first_token_ms = round(
                            (time.perf_counter() - generation_started) * 1000,
                            2,
                        )
                    yield {"type": "token", "content": content}
        except StreamCancelled:
            raise
        except Exception as exc:
            timings["llm_generation_ms"] = round(
                (time.perf_counter() - generation_started) * 1000,
                2,
            )
            timings["total_ms"] = round(
                (time.perf_counter() - total_started) * 1000,
                2,
            )
            self._log_timings(request_id, "stream_error", timings)
            yield {"type": "error", "message": str(exc)}
            return
        finally:
            close_stream = getattr(llm_stream, "close", None)
            if callable(close_stream):
                try:
                    close_stream()
                except Exception as exc:
                    logging.getLogger(__name__).warning("关闭 LLM 流失败: %s", exc)

        raise_if_cancelled(cancel_event, "after_llm_stream", request_id)
        timings["llm_first_token_ms"] = first_token_ms or 0.0
        timings["llm_generation_ms"] = round(
            (time.perf_counter() - generation_started) * 1000,
            2,
        )
        answer = "".join(answer_chunks)
        repaired = False
        if answer_verifier.enabled:
            raise_if_cancelled(
                cancel_event,
                "before_answer_verification",
                request_id,
            )
            verification_started = time.perf_counter()
            verified_answer, verification = answer_verifier.review_and_repair(
                question=question,
                answer=answer,
                documents=prepared.docs,
                history=prepared.input_data["history"],
            )
            timings["answer_verification_ms"] = round(
                (time.perf_counter() - verification_started) * 1000,
                2,
            )
            repaired = bool(verification.get("repaired"))
            timings["answer_repaired_count"] = float(repaired)
            if repaired:
                answer = verified_answer
        raise_if_cancelled(cancel_event, "before_final_response", request_id)
        timings["total_ms"] = round((time.perf_counter() - total_started) * 1000, 2)
        display_answer = applicability_notice + answer
        final_answer = append_source_footer(display_answer, prepared.docs)
        if repaired:
            yield {"type": "replace", "content": final_answer}
        source_footer = ""
        if not repaired:
            source_footer = build_new_source_footer(
                "".join(answer_chunks),
                prepared.docs,
            )
        raise_if_cancelled(cancel_event, "before_confidence", request_id)
        confidence = confidence_evaluator.evaluate(
            question,
            answer,
            prepared.docs,
            prepared.rewrite,
            prepared.input_data.get("retrieval_query"),
            coverage=prepared.coverage,
            query_plan=prepared.query_plan,
            applicability_scope=prepared.retrieval_scope,
        )
        if source_footer:
            yield {"type": "token", "content": source_footer}
        raise_if_cancelled(cancel_event, "before_memory_save", request_id)
        self._save_memory_turn(
            memory_context.thread_id,
            question,
            display_answer,
            timings,
        )
        yield {"type": "sources", "sources": prepared.sources}
        yield {"type": "timings", "timings": timings, "request_id": request_id}
        yield {"type": "confidence", "confidence": confidence.to_dict()}
        self._log_timings(request_id, "stream", timings)
        self._log_confidence(request_id, confidence.to_dict())

    @staticmethod
    def _confidence_payload(
        confidence: ConfidenceResult | dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(confidence, ConfidenceResult):
            return confidence.to_dict()
        return confidence

    @staticmethod
    def _clarification_confidence(prepared: PreparedChat) -> dict[str, Any]:
        query_plan = prepared.query_plan or {}
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
    def _log_timings(
        request_id: str,
        mode: str,
        timings: dict[str, float],
    ) -> None:
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
    def _log_confidence(request_id: str, confidence: dict[str, Any]) -> None:
        signals = confidence.get("signals", {})
        signal_text = " ".join(
            f"{key}={float(value):.4f}"
            for key, value in signals.items()
        )
        logging.getLogger(__name__).info(
            "answer_confidence request_id=%s overall=%.4f retrieval=%.4f "
            "generation=%.4f risk=%.4f action=%s %s reasons=%s",
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
