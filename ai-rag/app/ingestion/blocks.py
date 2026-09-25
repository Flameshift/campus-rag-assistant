"""格式解析与分块之间使用的统一中间结构。"""

from dataclasses import dataclass, field
from typing import Any

from langchain_core.documents import Document


def normalize_document_text(text: str) -> str:
    """统一换行和行尾空白，同时保留段落及列表换行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


@dataclass
class DocumentBlock:
    """所有文件格式解析后共用的结构块。"""

    content: str
    block_type: str = "paragraph"
    section_path: list[str] = field(default_factory=list)
    heading_level: int = 0
    parent_key: str = ""
    order_index: int = 0
    page_start: int | None = None
    page_end: int | None = None
    source: str = ""
    structure_confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_document(self, page_content: str | None = None, **metadata: Any) -> Document:
        """转换为 LangChain Document，并把元数据限制为向量库支持的类型。"""
        raw_metadata: dict[str, Any] = {
            "source": self.source,
            "block_type": self.block_type,
            "section_path": " > ".join(self.section_path),
            "heading_level": self.heading_level,
            "parent_key": self.parent_key,
            "order_index": self.order_index,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "structure_confidence": self.structure_confidence,
        }
        raw_metadata.update(self.metadata)
        raw_metadata.update(metadata)

        clean_metadata: dict[str, Any] = {}
        for key, value in raw_metadata.items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                clean_metadata[key] = value
            else:
                clean_metadata[key] = str(value)

        return Document(
            page_content=normalize_document_text(
                page_content if page_content is not None else self.content
            ),
            metadata=clean_metadata,
        )
