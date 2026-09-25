"""为现有 Chroma 分块补齐父级元数据。

该脚本只更新 metadata，不重新生成 Embedding，也不会改变分块正文。
执行前建议停止 Python 服务，避免检索器与向量库同时读写。
"""

import argparse
import sys
from pathlib import Path

from langchain_core.documents import Document

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Chunk  # noqa: E402
from app.parenting import assign_parent_metadata  # noqa: E402
from app.rag_service import rag_service  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="回填现有知识库的 parent_id 元数据")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写入")
    args = parser.parse_args()

    init_db()
    result = rag_service.vectorstore.get(include=["documents", "metadatas"])
    vector_ids = result.get("ids", [])
    documents = [
        Document(page_content=content, metadata=dict(metadata or {}))
        for content, metadata in zip(
            result.get("documents", []),
            result.get("metadatas", []),
        )
    ]

    ordered = sorted(
        zip(vector_ids, documents),
        key=lambda item: (
            str(item[1].metadata.get("source") or ""),
            int(item[1].metadata.get("order_index", 0) or 0),
            int(item[1].metadata.get("chunk_id", 0) or 0),
        ),
    )
    ordered_ids = [item[0] for item in ordered]
    ordered_documents = [item[1] for item in ordered]

    assign_parent_metadata(
        ordered_documents,
        target_chars=config.PARENT_GROUP_TARGET_CHARS,
        max_children=config.PARENT_GROUP_MAX_CHILDREN,
    )

    parent_ids = {
        document.metadata.get("parent_id")
        for document in ordered_documents
        if document.metadata.get("parent_id")
    }
    print(f"chunks={len(ordered_documents)} parents={len(parent_ids)}")
    if args.dry_run:
        return

    if not ordered_documents:
        print("知识库为空，无需回填")
        return

    rag_service.vectorstore._collection.update(
        ids=ordered_ids,
        metadatas=[document.metadata for document in ordered_documents],
    )

    with SessionLocal() as db:
        updated = 0
        for document in ordered_documents:
            chunk_id = document.metadata.get("chunk_id")
            if not chunk_id:
                continue
            updated += db.query(Chunk).filter_by(id=int(chunk_id)).update(
                {
                    "parent_id": document.metadata.get("parent_id"),
                    "parent_type": document.metadata.get("parent_type"),
                    "parent_order_index": document.metadata.get("parent_order_index"),
                }
            )
        db.commit()

    rag_service.refresh_retriever()
    print(f"vector_metadata_updated={len(ordered_documents)} db_rows_updated={updated}")


if __name__ == "__main__":
    main()
