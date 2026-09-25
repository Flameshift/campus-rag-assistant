"""规则优先的章节、表格、记录和递归分块器。"""

import hashlib
from collections import defaultdict

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .. import config
from ..parenting import assign_parent_metadata
from .blocks import DocumentBlock, normalize_document_text


class StructureAwareChunker:
    """根据 DocumentBlock 类型选择对应分块策略。"""

    def __init__(self) -> None:
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP,
            separators=config.CHUNK_SEPARATOR,
            length_function=len,
        )
        self.record_splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.CHUNK_RECORD_MAX_SIZE,
            chunk_overlap=min(config.CHUNK_OVERLAP, config.CHUNK_RECORD_MAX_SIZE // 4),
            separators=["\n", "。", "；", "，", " ", ""],
            length_function=len,
        )

    def split(self, blocks: list[DocumentBlock]) -> list[Document]:
        if not blocks:
            return []

        documents: list[Document] = []
        buffer: list[DocumentBlock] = []
        buffer_size = 0

        def flush() -> None:
            nonlocal buffer_size
            if not buffer:
                return
            documents.extend(self._split_section(buffer))
            buffer.clear()
            buffer_size = 0

        for block in blocks:
            if block.block_type in {"record", "table", "code"}:
                flush()
                documents.extend(self._split_special(block))
                continue

            if buffer and (
                block.parent_key != buffer[-1].parent_key
                or buffer_size + len(block.content) > config.CHUNK_SIZE * 2
            ):
                flush()

            buffer.append(block)
            buffer_size += len(block.content)

        flush()
        documents = self._renumber(documents)
        return assign_parent_metadata(
            documents,
            target_chars=config.PARENT_GROUP_TARGET_CHARS,
            max_children=config.PARENT_GROUP_MAX_CHILDREN,
        )

    def _split_section(self, blocks: list[DocumentBlock]) -> list[Document]:
        text = normalize_document_text("\n\n".join(block.content for block in blocks))
        if not text:
            return []

        pieces = self.text_splitter.split_text(text)
        return [
            self._make_document(piece, blocks, strategy="section", child_index=index)
            for index, piece in enumerate(pieces)
            if piece.strip()
        ]

    def _split_special(self, block: DocumentBlock) -> list[Document]:
        if block.block_type == "table":
            pieces = self._split_table(block.content)
            strategy = "table"
        elif block.block_type == "record":
            pieces = self.record_splitter.split_text(block.content)
            strategy = "record"
        else:
            pieces = self.text_splitter.split_text(block.content)
            strategy = "code"

        return [
            self._make_document(piece, [block], strategy=strategy, child_index=index)
            for index, piece in enumerate(pieces)
            if piece.strip()
        ]

    def _split_table(self, content: str) -> list[str]:
        lines = [line for line in content.splitlines() if line.strip()]
        if len(content) <= config.CHUNK_SIZE or len(lines) <= 3:
            return [content]

        header = lines[:2]
        rows = lines[2:]
        group_size = max(1, config.CHUNK_TABLE_ROWS_PER_GROUP)
        return [
            "\n".join(header + rows[index : index + group_size])
            for index in range(0, len(rows), group_size)
        ]

    def _make_document(
        self,
        content: str,
        blocks: list[DocumentBlock],
        strategy: str,
        child_index: int,
    ) -> Document:
        first = blocks[0]
        section_path = first.section_path
        section_text = " > ".join(section_path)
        final_content = content
        if config.CHUNK_INCLUDE_SECTION_PATH and section_text:
            final_content = f"【章节】{section_text}\n\n{content}"

        page_values = [
            value
            for block in blocks
            for value in (block.page_start, block.page_end)
            if isinstance(value, int)
        ]
        logical_hash = hashlib.sha256(
            (
                f"{config.PARSER_VERSION}|{config.CHUNKER_VERSION}|"
                f"{first.source}|{section_text}|{strategy}|{content}"
            ).encode("utf-8")
        ).hexdigest()

        return first.to_document(
            page_content=final_content,
            chunk_strategy=strategy,
            child_index=child_index,
            page_start=min(page_values) if page_values else None,
            page_end=max(page_values) if page_values else None,
            parser_version=config.PARSER_VERSION,
            chunker_version=config.CHUNKER_VERSION,
            logical_hash=logical_hash,
        )

    @staticmethod
    def _renumber(documents: list[Document]) -> list[Document]:
        """保证同一文件内的分块顺序稳定，供相邻分块扩展使用。"""
        counters: dict[str, int] = defaultdict(int)
        for document in documents:
            source = str(document.metadata.get("source", ""))
            document.metadata["order_index"] = counters[source]
            counters[source] += 1
        return documents
