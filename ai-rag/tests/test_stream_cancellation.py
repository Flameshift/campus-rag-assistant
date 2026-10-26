"""流式问答取消传播测试。"""

import threading
import unittest

from starlette.requests import ClientDisconnect

from app.main import CancellableStreamingResponse
from app.rag_service import RagService, StreamCancelled
from app.short_term_memory import MemoryContext


class _FakeChunk:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChatChain:
    def __init__(self) -> None:
        self.second_token_requested = False
        self.closed = False

    def stream(self, _input_data):
        try:
            yield _FakeChunk("first")
            self.second_token_requested = True
            yield _FakeChunk("second")
        finally:
            self.closed = True


class StreamCancellationTests(unittest.TestCase):
    def _build_service(self, chain: _FakeChatChain, saved: list[tuple[str, str]]):
        service = object.__new__(RagService)
        service.chat_chain = chain
        service._load_memory_context = lambda *_args, **_kwargs: MemoryContext(
            "thread:test",
            [{"role": "user", "content": "history"}],
            True,
        )
        service._prepare_chat = lambda *_args, **_kwargs: {
            "docs": [],
            "sources": [],
            "timings": {},
            "input_data": {
                "docs": [],
                "question": "question",
                "history": "",
                "retrieval_query": "question",
            },
            "query_plan": {},
            "coverage": {},
            "retrieval_scope": {},
            "applicability_notice": "",
        }
        service._save_memory_turn = lambda _thread_id, question, answer, _timings: saved.append(
            (question, answer)
        )
        return service

    def test_pre_cancelled_stream_stops_before_memory_and_retrieval(self):
        cancel_event = threading.Event()
        cancel_event.set()
        chain = _FakeChatChain()
        saved: list[tuple[str, str]] = []
        service = self._build_service(chain, saved)

        with self.assertRaises(StreamCancelled):
            next(
                service.stream_chat(
                    "question",
                    [],
                    thread_id="thread:test",
                    cancel_event=cancel_event,
                )
            )

        self.assertFalse(chain.second_token_requested)
        self.assertEqual(saved, [])

    def test_cancel_after_first_token_does_not_request_second_token(self):
        cancel_event = threading.Event()
        chain = _FakeChatChain()
        saved: list[tuple[str, str]] = []
        service = self._build_service(chain, saved)
        stream = service.stream_chat(
            "question",
            [],
            thread_id="thread:test",
            cancel_event=cancel_event,
        )

        self.assertEqual(next(stream)["type"], "status")
        self.assertEqual(next(stream), {"type": "token", "content": "first"})

        cancel_event.set()
        with self.assertRaises(StreamCancelled):
            next(stream)

        self.assertFalse(chain.second_token_requested)
        self.assertTrue(chain.closed)
        self.assertEqual(saved, [])


class CancellableStreamingResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_failure_closes_async_generator(self):
        closed = threading.Event()

        async def body():
            try:
                yield "data: first\n\n"
            finally:
                closed.set()

        response = CancellableStreamingResponse(
            body(),
            media_type="text/event-stream",
        )

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("client disconnected")

        with self.assertRaises(ClientDisconnect):
            await response(
                {"type": "http", "asgi": {"spec_version": "2.4"}},
                receive,
                send,
            )

        self.assertTrue(closed.is_set())


if __name__ == "__main__":
    unittest.main()
