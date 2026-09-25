"""基于数据库任务记录的后台任务队列。

当前实现使用进程内线程池，接口与任务状态已持久化，后续可替换为 Redis Stream、
RabbitMQ 或 Celery，而不改变接口层。
"""

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import models
from .db import SessionLocal

logger = logging.getLogger(__name__)


class TaskQueue:
    def __init__(self, workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, workers),
            thread_name_prefix="rag-task",
        )
        self._lock = threading.Lock()

    def submit(self, task_type: str, source_file_id: int | None, runner) -> str:
        task_id = f"{task_type}-{uuid.uuid4().hex[:16]}"
        with self._lock, SessionLocal() as db:
            db.add(
                models.UploadJob(
                    upload_id=task_id,
                    source_file_id=source_file_id,
                    task_type=task_type,
                    status="queued",
                    progress=0,
                )
            )
            db.commit()
        self._executor.submit(self._run, task_id, runner)
        return task_id

    def _run(self, task_id: str, runner) -> None:
        self._update(task_id, status="processing", progress=5)
        try:
            result = runner(task_id)
        except Exception as exc:
            logger.exception("后台任务失败: task_id=%s", task_id)
            self._update(
                task_id,
                status="failed",
                progress=0,
                error=str(exc),
            )
            return
        self._update(
            task_id,
            status="done",
            progress=100,
            error="" if result is None else str(result),
        )

    @staticmethod
    def _update(
        task_id: str,
        status: str,
        progress: int,
        error: str = "",
    ) -> None:
        with SessionLocal() as db:
            task = db.query(models.UploadJob).filter_by(upload_id=task_id).first()
            if task is None:
                return
            task.status = status
            task.progress = progress
            if error:
                task.error = error
            task.updated_at = datetime.now(timezone.utc)
            db.commit()


task_queue = TaskQueue()
