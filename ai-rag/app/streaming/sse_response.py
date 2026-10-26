"""支持客户端断连清理的 StreamingResponse。"""

import logging
from collections.abc import Awaitable, Callable
from typing import cast

import anyio
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


class CancellableStreamingResponse(StreamingResponse):
    """确保客户端断开时关闭异步 SSE 生成器和其后的同步 RAG 生成器。"""

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # 断开响应时普通 return 不一定会立刻回收 async generator，
            # 这里显式 aclose，确保 event_stream 的 finally 能执行。
            with anyio.CancelScope(shield=True):
                close = getattr(self.body_iterator, "aclose", None)
                if callable(close):
                    try:
                        await cast(Callable[[], Awaitable[None]], close)()
                    except Exception as exc:
                        logger.warning("关闭流式生成器失败: %s", exc)
