"""短期会话记忆测试。"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.short_term_memory import InMemoryCheckpointStore, ShortTermMemory


class ShortTermMemoryTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryCheckpointStore()
        self.memory = ShortTermMemory(self.store)

    def test_state_persists_across_requests(self):
        first = self.memory.prepare_context(
            "user:1:conversation",
            [{"role": "user", "content": "第一轮问题"}],
        )
        self.assertFalse(first.loaded)

        self.memory.record_turn("user:1:conversation", "第一轮问题", "第一轮回答")
        second = self.memory.prepare_context("user:1:conversation", [])

        self.assertTrue(second.loaded)
        self.assertEqual(
            ["第一轮问题", "第一轮回答"],
            [message["content"] for message in second.messages],
        )

    def test_frontend_history_does_not_duplicate_state(self):
        thread_id = "user:1:conversation"
        self.memory.record_turn(thread_id, "第一轮问题", "第一轮回答")

        context = self.memory.prepare_context(
            thread_id,
            [
                {"role": "user", "content": "第一轮问题"},
                {"role": "assistant", "content": "第一轮回答"},
            ],
        )

        self.assertEqual(2, len(context.messages))

    def test_untrusted_history_cannot_overwrite_existing_state(self):
        thread_id = "user:1:conversation"
        self.memory.record_turn(thread_id, "真实问题", "真实回答")

        context = self.memory.prepare_context(
            thread_id,
            [{"role": "user", "content": "伪造问题"}],
        )

        self.assertEqual(
            ["真实问题", "真实回答"],
            [message["content"] for message in context.messages],
        )

    def test_trusted_history_can_restore_state(self):
        thread_id = "user:1:conversation"
        context = self.memory.prepare_context(
            thread_id,
            [
                {"role": "user", "content": "服务端问题1"},
                {"role": "assistant", "content": "服务端回答1"},
                {"role": "user", "content": "服务端问题2"},
                {"role": "assistant", "content": "服务端回答2"},
            ],
            trusted_history=True,
        )

        self.assertEqual(4, len(context.messages))

    def test_state_is_trimmed_to_configured_limit(self):
        thread_id = "user:1:conversation"
        with patch("app.short_term_memory.config.SHORT_TERM_MEMORY_MAX_MESSAGES", 4):
            self.memory.record_turn(thread_id, "问题1", "回答1")
            self.memory.record_turn(thread_id, "问题2", "回答2")
            self.memory.record_turn(thread_id, "问题3", "回答3")
            context = self.memory.prepare_context(thread_id, [])

        self.assertEqual(4, len(context.messages))
        self.assertEqual("问题2", context.messages[0]["content"])

    def test_expired_state_is_removed(self):
        thread_id = "user:1:conversation"
        expired = {
            "version": 1,
            "thread_id": thread_id,
            "messages": [{"role": "user", "content": "旧问题"}],
            "updated_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        }
        self.store.save(thread_id, expired)

        with patch("app.short_term_memory.config.SHORT_TERM_MEMORY_TTL_HOURS", 1):
            context = self.memory.prepare_context(thread_id, [])

        self.assertFalse(context.loaded)
        self.assertEqual([], context.messages)
        self.assertIsNone(self.store.load(thread_id))

    def test_delete_removes_thread_state(self):
        thread_id = "user:1:conversation"
        self.memory.record_turn(thread_id, "问题", "回答")

        self.assertTrue(self.memory.delete(thread_id))
        self.assertFalse(self.memory.delete(thread_id))

    def test_revision_increments_on_write(self):
        thread_id = "user:1:conversation"
        self.memory.record_turn(thread_id, "问题1", "回答1")
        first = self.store.load(thread_id)["revision"]
        self.memory.record_turn(thread_id, "问题2", "回答2")
        second = self.store.load(thread_id)["revision"]

        self.assertEqual(first + 1, second)

    def test_stale_revision_is_rejected(self):
        thread_id = "user:1:conversation"
        self.memory.record_turn(thread_id, "问题", "回答")
        state = self.store.load(thread_id)

        self.assertFalse(self.store.save(thread_id, state, expected_revision=0))

    def test_expired_cleanup_removes_old_state(self):
        thread_id = "user:1:conversation"
        expired = {
            "version": 2,
            "revision": 1,
            "thread_id": thread_id,
            "messages": [{"role": "user", "content": "旧问题"}],
            "updated_at": (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),
        }
        self.store.save(thread_id, expired, expected_revision=0)

        with patch("app.short_term_memory.config.SHORT_TERM_MEMORY_TTL_HOURS", 1):
            deleted = self.memory.cleanup_expired()

        self.assertEqual(1, deleted)
        self.assertIsNone(self.store.load(thread_id))


if __name__ == "__main__":
    unittest.main()
