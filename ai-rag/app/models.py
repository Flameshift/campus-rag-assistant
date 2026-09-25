# ORM 模型：source_file / chunk / upload_job 三张核心表。
# 大型项目建议在此基础上扩展分区、索引和审计字段。

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceFile(Base):
    """上传文件记录：hash 唯一，用于文件级去重。"""

    __tablename__ = "source_file"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 文件内容 SHA-256；唯一索引保证同一文件只入库一次。
    hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="文件内容 SHA-256")
    file_name: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    document_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    document_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    document_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    issuing_department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    effective_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expiry_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    supersedes: Mapped[str | None] = mapped_column(Text, nullable=True)
    applicability: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_aliases: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    version_status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uploader_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    # 状态：pending / processing / done / failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="source_file")


class Chunk(Base):
    """知识分块记录：content_hash 唯一，用于分块级去重。"""

    __tablename__ = "chunk"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 归一化后的内容哈希；唯一索引并发写入时也只会保留一份。
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="分块内容哈希")
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_file.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    # 向量库中的主键；写入 Chroma/Milvus 后回填，便于后续清理。
    vector_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 语义重复时指向 canonical chunk；为空表示该分块本身是正式分块。
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("chunk.id"), nullable=True, index=True
    )
    # 与 canonical chunk 的余弦相似度，仅语义重复记录会写入。
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 结构化分块信息：用于父子扩展、相邻片段召回和策略版本追踪。
    logical_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    parent_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    parent_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parent_order_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    node_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chunker_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    source_file: Mapped[SourceFile] = relationship(back_populates="chunks")


class UploadJob(Base):
    """上传任务记录：upload_id 唯一，用于幂等与异步处理。"""

    __tablename__ = "upload_job"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 客户端生成的幂等键；唯一索引保证重复提交只处理一次。
    upload_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("source_file.id"), nullable=True)
    # 状态：pending / processing / done / failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    task_type: Mapped[str] = mapped_column(String(32), default="upload")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ShortTermCheckpoint(Base):
    """按 thread_id 保存最新的短期对话状态。"""

    __tablename__ = "short_term_checkpoint"

    thread_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    state: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        index=True,
    )
