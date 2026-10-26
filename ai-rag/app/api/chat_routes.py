"""问答、SSE 和短期记忆接口。"""

import json
import logging
import threading

from fastapi import APIRouter, HTTPException
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from ..rag_service import StreamCancelled, rag_service
from ..schemas import ChatRequest, ChatResponse, Source
from ..short_term_memory import short_term_memory
from ..streaming import CancellableStreamingResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """非流式问答接口。"""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    history = [item.model_dump() for item in req.history]
    answer, sources, mode, timings, request_id, confidence = rag_service.chat(
        req.question,
        history,
        thread_id=req.thread_id,
        history_trusted=req.history_trusted,
    )
    return ChatResponse(
        answer=answer,
        sources=[Source(**source) for source in sources],
        mode=mode,
        timings=timings,
        request_id=request_id,
        confidence=confidence,
    )


@router.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    """SSE 流式问答接口。"""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    history = [item.model_dump() for item in req.history]

    cancel_event = threading.Event()
    rag_stream = rag_service.stream_chat(
        req.question,
        history,
        thread_id=req.thread_id,
        history_trusted=req.history_trusted,
        cancel_event=cancel_event,
    )

    async def event_stream():
        """把同步 RAG 事件转成异步 SSE，并保证断连时关闭底层生成器。"""
        try:
            async for event in iterate_in_threadpool(rag_stream):
                if cancel_event.is_set():
                    return
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            if not cancel_event.is_set():
                yield 'data: {"type": "done"}\n\n'
        except StreamCancelled as exc:
            logger.info("chat_stream_cancelled stage=%s", exc.stage)
        finally:
            cancel_event.set()
            close = getattr(rag_stream, "close", None)
            if callable(close):
                try:
                    await run_in_threadpool(close)
                except Exception as exc:
                    logger.warning("关闭 RAG 流失败: %s", exc)

    return CancellableStreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/api/memory/{thread_id}")
def delete_short_term_memory(thread_id: str):
    """删除指定 thread_id 的短期会话记忆。"""
    deleted = short_term_memory.delete(thread_id)
    return {"thread_id": thread_id, "deleted": deleted}
