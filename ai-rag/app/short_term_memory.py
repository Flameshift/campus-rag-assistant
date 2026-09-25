"""基于 thread_id 的短期会话记忆。

该模块提供 LangGraph 风格的 State/Checkpointer 语义，但保持存储层可替换。
当前使用 SQLAlchemy 数据库作为轻量 Checkpointer，后续可以替换为
LangGraph 的 SqliteSaver、PostgresSaver 或 Redis Checkpointer。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from langchain_core.documents import Document

from . import config
from .db import SessionLocal
from sqlalchemy.exc import IntegrityError

from .models import ShortTermCheckpoint

STATE_VERSION = 2
logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utcnow().isoformat()


def _empty_state(thread_id: str) -> dict:
    return {
        "version": STATE_VERSION,
        "revision": 0,
        "thread_id": thread_id,
        "messages": [],
        "rolling_summary": "",
        "entities": {},
        "current_task": "",
        "pending_question": "",
        "updated_at": _iso_now(),
    }


def _message_key(message: dict) -> tuple[str, str]:
    return (
        str(message.get("role") or "").strip(),
        str(message.get("content") or "").strip(),
    )


def _normalize_messages(messages: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        content = str(message.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _merge_messages(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """合并完整前端历史和已持久化历史，避免重复追加相同对话。"""
    if not existing:
        return list(incoming)
    if not incoming:
        return list(existing)

    existing_keys = [_message_key(message) for message in existing]
    incoming_keys = [_message_key(message) for message in incoming]

    if len(incoming_keys) >= len(existing_keys):
        for start in range(0, len(incoming_keys) - len(existing_keys) + 1):
            if incoming_keys[start : start + len(existing_keys)] == existing_keys:
                return list(incoming)

    if len(existing_keys) >= len(incoming_keys):
        for start in range(0, len(existing_keys) - len(incoming_keys) + 1):
            if existing_keys[start : start + len(incoming_keys)] == incoming_keys:
                return list(existing)

    max_overlap = min(len(existing_keys), len(incoming_keys))
    for overlap in range(max_overlap, 0, -1):
        if existing_keys[-overlap:] == incoming_keys[:overlap]:
            return list(existing) + list(incoming[overlap:])
    return list(existing) + list(incoming)


class CheckpointStore(Protocol):
    """短期状态存储协议。"""

    def load(self, thread_id: str) -> dict | None:
        ...

    def save(
        self,
        thread_id: str,
        state: dict,
        expected_revision: int | None = None,
    ) -> bool:
        ...

    def delete(self, thread_id: str) -> None:
        ...

    def delete_expired(self, before: datetime) -> int:
        ...


class SQLAlchemyCheckpointStore:
    """使用现有数据库保存 thread_id 对应的最新状态。"""

    def load(self, thread_id: str) -> dict | None:
        with SessionLocal() as db:
            checkpoint = db.get(ShortTermCheckpoint, thread_id)
            if checkpoint is None:
                return None
            try:
                state = json.loads(checkpoint.state or "{}")
            except (TypeError, ValueError):
                return None
            if not isinstance(state, dict):
                return None
            return state

    def save(
        self,
        thread_id: str,
        state: dict,
        expected_revision: int | None = None,
    ) -> bool:
        payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        with SessionLocal() as db:
            checkpoint = db.get(ShortTermCheckpoint, thread_id)
            current_revision = checkpoint.revision if checkpoint is not None else 0
            if expected_revision is not None and current_revision != expected_revision:
                return False
            if checkpoint is None:
                checkpoint = ShortTermCheckpoint(
                    thread_id=thread_id,
                    state=payload,
                    version=STATE_VERSION,
                    revision=int(state.get("revision", 1)),
                )
                db.add(checkpoint)
            else:
                checkpoint.state = payload
                checkpoint.version = STATE_VERSION
                checkpoint.revision = int(state.get("revision", current_revision + 1))
                checkpoint.updated_at = _utcnow()
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return False
            return True

    def delete(self, thread_id: str) -> None:
        with SessionLocal() as db:
            checkpoint = db.get(ShortTermCheckpoint, thread_id)
            if checkpoint is not None:
                db.delete(checkpoint)
                db.commit()

    def delete_expired(self, before: datetime) -> int:
        with SessionLocal() as db:
            deleted = (
                db.query(ShortTermCheckpoint)
                .filter(ShortTermCheckpoint.updated_at < before)
                .delete(synchronize_session=False)
            )
            db.commit()
            return int(deleted)


class InMemoryCheckpointStore:
    """测试和本地适配使用的内存 Checkpointer。"""

    def __init__(self) -> None:
        self._states: dict[str, dict] = {}

    def load(self, thread_id: str) -> dict | None:
        state = self._states.get(thread_id)
        return json.loads(json.dumps(state)) if state is not None else None

    def save(
        self,
        thread_id: str,
        state: dict,
        expected_revision: int | None = None,
    ) -> bool:
        current = self._states.get(thread_id)
        current_revision = int((current or {}).get("revision", 0))
        if expected_revision is not None and current_revision != expected_revision:
            return False
        self._states[thread_id] = json.loads(json.dumps(state))
        return True

    def delete(self, thread_id: str) -> None:
        self._states.pop(thread_id, None)

    def delete_expired(self, before: datetime) -> int:
        expired = []
        for thread_id, state in self._states.items():
            try:
                updated_at = datetime.fromisoformat(
                    str(state.get("updated_at", "")).replace("Z", "+00:00")
                )
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
            except ValueError:
                expired.append(thread_id)
                continue
            if updated_at < before:
                expired.append(thread_id)
        for thread_id in expired:
            self._states.pop(thread_id, None)
        return len(expired)


@dataclass
class MemoryContext:
    thread_id: str | None
    messages: list[dict]
    loaded: bool


class ShortTermMemory:
    """按 thread_id 管理短期对话状态。"""

    def __init__(self, store: CheckpointStore | None = None) -> None:
        self.store = store or SQLAlchemyCheckpointStore()
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._cleanup_stop = threading.Event()
        self._cleanup_thread: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return config.SHORT_TERM_MEMORY_ENABLED

    def prepare_context(
        self,
        thread_id: str | None,
        request_history: list[dict],
        trusted_history: bool = False,
    ) -> MemoryContext:
        """返回供 Query Rewrite 和 Prompt 使用的短期上下文。"""
        history = _normalize_messages(request_history)
        if not self.enabled or not thread_id:
            return MemoryContext(None, history[-config.SHORT_TERM_CONTEXT_MESSAGES :], False)

        normalized_thread_id = str(thread_id).strip()[:128]
        if not normalized_thread_id:
            return MemoryContext(None, history[-config.SHORT_TERM_CONTEXT_MESSAGES :], False)

        with self._lock(normalized_thread_id):
            state = self._load_valid_state(normalized_thread_id)
            loaded = state is not None
            previous_revision = self._revision(state) if state is not None else 0
            if state is None:
                if not history:
                    return MemoryContext(normalized_thread_id, [], False)
                state = _empty_state(normalized_thread_id)
                state["messages"] = history[-config.SHORT_TERM_MEMORY_MAX_MESSAGES :]
                state["revision"] = 1
            elif trusted_history and history:
                # 登录用户的 Spring Boot 消息表是权威来源。
                state["messages"] = history[-config.SHORT_TERM_MEMORY_MAX_MESSAGES :]
                state["revision"] = previous_revision + 1
            else:
                state["messages"] = _normalize_messages(state.get("messages"))
                state["revision"] = previous_revision
            state["updated_at"] = _iso_now()
            self._save_with_retry(
                normalized_thread_id,
                state,
                expected_revision=previous_revision,
            )

        return MemoryContext(
            normalized_thread_id,
            state["messages"][-config.SHORT_TERM_CONTEXT_MESSAGES :],
            loaded,
        )

    def record_turn(self, thread_id: str | None, question: str, answer: str) -> None:
        """在回答完成后写入当前用户消息和助手消息。"""
        if not self.enabled or not thread_id:
            return
        normalized_thread_id = str(thread_id).strip()[:128]
        if not normalized_thread_id:
            return

        question = str(question or "").strip()
        answer = str(answer or "").strip()
        if not question or not answer:
            return

        with self._lock(normalized_thread_id):
            for _ in range(3):
                state = self._load_valid_state(normalized_thread_id) or _empty_state(
                    normalized_thread_id
                )
                revision = self._revision(state)
                messages = _normalize_messages(state.get("messages"))
                turn = [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                ]
                messages = _merge_messages(messages, turn)
                state["messages"] = messages[-config.SHORT_TERM_MEMORY_MAX_MESSAGES :]
                state["revision"] = revision + 1
                state["updated_at"] = _iso_now()
                if self.store.save(
                    normalized_thread_id,
                    state,
                    expected_revision=revision,
                ):
                    return
            logger.warning("短期记忆写入冲突，已放弃本轮更新: thread_id=%s", normalized_thread_id)

    def delete(self, thread_id: str) -> bool:
        if not thread_id:
            return False
        normalized_thread_id = str(thread_id).strip()[:128]
        if not normalized_thread_id:
            return False
        with self._lock(normalized_thread_id):
            state = self.store.load(normalized_thread_id)
            if state is None:
                return False
            self.store.delete(normalized_thread_id)
            return True

    def start_background_cleanup(self) -> None:
        """启动 TTL 清理线程。"""
        if not self.enabled or self._cleanup_thread is not None:
            return
        self._cleanup_stop.clear()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="short-term-memory-cleanup",
            daemon=True,
        )
        self._cleanup_thread.start()

    def stop_background_cleanup(self) -> None:
        self._cleanup_stop.set()
        if self._cleanup_thread is not None:
            self._cleanup_thread.join(timeout=2)
            self._cleanup_thread = None

    def cleanup_expired(self) -> int:
        if not self.enabled or config.SHORT_TERM_MEMORY_TTL_HOURS <= 0:
            return 0
        before = _utcnow().replace(microsecond=0)
        before = before.timestamp() - config.SHORT_TERM_MEMORY_TTL_HOURS * 3600
        cutoff = datetime.fromtimestamp(before, tz=timezone.utc)
        return self.store.delete_expired(cutoff)

    def _cleanup_loop(self) -> None:
        interval = max(60, config.SHORT_TERM_MEMORY_CLEANUP_INTERVAL_SECONDS)
        while not self._cleanup_stop.is_set():
            try:
                deleted = self.cleanup_expired()
                if deleted:
                    logger.info("短期记忆 TTL 清理完成: deleted=%s", deleted)
            except Exception as exc:
                logger.warning("短期记忆 TTL 清理失败: %s", exc)
            self._cleanup_stop.wait(interval)

    def _load_valid_state(self, thread_id: str) -> dict | None:
        state = self.store.load(thread_id)
        if state is None:
            return None
        if not self._is_fresh(state):
            self.store.delete(thread_id)
            return None
        return state

    def _save_with_retry(
        self,
        thread_id: str,
        state: dict,
        expected_revision: int,
    ) -> bool:
        for _ in range(3):
            if self.store.save(thread_id, state, expected_revision=expected_revision):
                return True
            current = self._load_valid_state(thread_id)
            if current is None:
                expected_revision = 0
            else:
                expected_revision = self._revision(current)
                state["revision"] = expected_revision + 1
        return False

    @staticmethod
    def _revision(state: dict) -> int:
        try:
            return int(state.get("revision", 0))
        except (TypeError, ValueError):
            return 0

    def _lock(self, thread_id: str) -> threading.RLock:
        with self._locks_guard:
            lock = self._locks.get(thread_id)
            if lock is None:
                lock = threading.RLock()
                self._locks[thread_id] = lock
            return lock

    @staticmethod
    def _is_fresh(state: dict) -> bool:
        ttl = config.SHORT_TERM_MEMORY_TTL_HOURS
        if ttl <= 0:
            return True
        value = state.get("updated_at")
        if not value:
            return False
        try:
            updated_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        return (_utcnow() - updated_at).total_seconds() <= ttl * 3600


short_term_memory = ShortTermMemory()
