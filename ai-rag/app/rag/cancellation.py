"""RAG 流式生成取消控制。"""

import logging
import threading

logger = logging.getLogger(__name__)


class StreamCancelled(Exception):
    """客户端已断开时用于终止流式生成内部流程。"""

    def __init__(self, stage: str) -> None:
        super().__init__(f"stream cancelled at {stage}")
        self.stage = stage


def raise_if_cancelled(
    cancel_event: threading.Event | None,
    stage: str,
    request_id: str | None = None,
) -> None:
    """在耗时阶段边界检查取消标记，并立即停止后续生成。"""
    if cancel_event is None or not cancel_event.is_set():
        return
    logger.info(
        "chat_stream_cancelled request_id=%s stage=%s",
        request_id or "-",
        stage,
    )
    raise StreamCancelled(stage)
