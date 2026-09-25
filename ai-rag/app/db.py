# 数据库基础配置：默认 SQLite 方便本地开发，生产环境改成 PostgreSQL。

import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# 通过 .env 中的 DATABASE_URL 覆盖，例如：
# postgresql+psycopg://user:pass@localhost:5432/ai_rag
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")

# SQLite 需要关闭多线程检查；其他数据库使用默认连接参数。
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)

# 会话工厂：每个请求/任务创建独立会话。
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的公共基类。"""


def init_db():
    """初始化数据表。生产环境建议改用 Alembic 迁移管理表结构。"""
    from . import models  # 确保模型注册到 Base.metadata

    Base.metadata.create_all(bind=engine)
    _ensure_structured_chunk_columns()
    _ensure_short_term_memory_columns()
    _ensure_source_file_columns()
    _ensure_upload_job_columns()


def _ensure_structured_chunk_columns() -> None:
    """为已有 SQLite/MySQL 数据库补充结构化分块字段。

    这是当前轻量项目的兼容迁移。正式生产环境应改为 Alembic 迁移。
    """
    inspector = inspect(engine)
    if "chunk" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("chunk")}
    missing_columns = {
        "logical_hash": "VARCHAR(64)",
        "parent_key": "VARCHAR(64)",
        "parent_id": "VARCHAR(64)",
        "parent_type": "VARCHAR(32)",
        "parent_order_index": "INTEGER",
        "node_type": "VARCHAR(32)",
        "section_path": "TEXT",
        "order_index": "INTEGER",
        "page_start": "INTEGER",
        "page_end": "INTEGER",
        "parser_version": "VARCHAR(32)",
        "chunker_version": "VARCHAR(32)",
    }

    with engine.begin() as connection:
        for name, column_type in missing_columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE chunk ADD COLUMN {name} {column_type}"))


def _ensure_short_term_memory_columns() -> None:
    """为已有短期记忆表补充状态版本字段。"""
    inspector = inspect(engine)
    if "short_term_checkpoint" not in inspector.get_table_names():
        return

    existing = {
        column["name"]
        for column in inspector.get_columns("short_term_checkpoint")
    }
    if "revision" in existing:
        return

    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE short_term_checkpoint ADD COLUMN revision INTEGER DEFAULT 0")
        )


def _ensure_source_file_columns() -> None:
    """为已有知识库源文件补充上传人字段。"""
    inspector = inspect(engine)
    if "source_file" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("source_file")}
    missing_columns = {
        "document_id": "VARCHAR(64)",
        "document_title": "VARCHAR(255)",
        "document_number": "VARCHAR(64)",
        "document_type": "VARCHAR(32)",
        "issuing_department": "VARCHAR(128)",
        "effective_date": "VARCHAR(32)",
        "expiry_date": "VARCHAR(32)",
        "supersedes": "TEXT",
        "applicability": "TEXT",
        "document_aliases": "TEXT",
        "version": "INTEGER DEFAULT 1",
        "version_status": "VARCHAR(20) DEFAULT 'active'",
        "is_current": "BOOLEAN DEFAULT 1",
        "uploaded_by_user_id": "BIGINT",
        "uploader_name": "VARCHAR(64)",
        "uploaded_at": "TIMESTAMP",
        "updated_by_user_id": "BIGINT",
        "updated_at": "TIMESTAMP",
    }
    with engine.begin() as connection:
        for name, column_type in missing_columns.items():
            if name not in existing:
                connection.execute(
                    text(f"ALTER TABLE source_file ADD COLUMN {name} {column_type}")
                )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE source_file SET document_id = 'doc-' || id "
                "WHERE document_id IS NULL OR document_id = ''"
            )
        )
        connection.execute(
            text(
                "UPDATE source_file SET document_title = file_name "
                "WHERE document_title IS NULL OR document_title = ''"
            )
        )


def _ensure_upload_job_columns() -> None:
    """为任务表补充类型和进度字段。"""
    inspector = inspect(engine)
    if "upload_job" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("upload_job")}
    missing_columns = {
        "task_type": "VARCHAR(32) DEFAULT 'upload'",
        "progress": "INTEGER DEFAULT 0",
    }
    with engine.begin() as connection:
        for name, column_type in missing_columns.items():
            if name not in existing:
                connection.execute(
                    text(f"ALTER TABLE upload_job ADD COLUMN {name} {column_type}")
                )
