"""结构化摄取编排：解析、结构分析、可选 LLM 规划和分块。"""

from langchain_core.documents import Document

from .blocks import DocumentBlock
from .chunking import StructureAwareChunker
from .loaders import blocks_from_text, load_blocks_from_file
from .llm_planner import StructureLLMPlanner
from .structure import StructureAnalyzer


class IngestionService:
    """统一入口，保证所有文件都经过同一套结构流程。"""

    def __init__(self) -> None:
        self.analyzer = StructureAnalyzer()
        self.planner = StructureLLMPlanner()
        self.chunker = StructureAwareChunker()

    def load_and_split(self, filename: str, content: bytes) -> list[Document]:
        blocks = load_blocks_from_file(filename, content)
        return self._split_blocks(blocks, filename)

    def split_text(self, text: str, metadata: dict | None = None) -> list[Document]:
        metadata = metadata or {}
        source = str(metadata.get("source", "text.txt"))
        blocks = blocks_from_text(text, source)
        for block in blocks:
            block.metadata.update({key: value for key, value in metadata.items() if key != "source"})
        return self._split_blocks(blocks, source)

    def split_documents(self, documents: list[Document]) -> list[Document]:
        """兼容已有 LangChain Loader 输出。"""
        all_blocks: list[DocumentBlock] = []
        for document in documents:
            source = str(document.metadata.get("source", "document.txt"))
            page = document.metadata.get("page")
            page_number = int(page) + 1 if isinstance(page, int) else None
            blocks = blocks_from_text(document.page_content, source)
            for block in blocks:
                block.page_start = page_number
                block.page_end = page_number
                block.metadata.update(document.metadata)
            all_blocks.extend(blocks)
        return self._split_blocks(all_blocks, "document")

    def _split_blocks(self, blocks: list[DocumentBlock], source: str) -> list[Document]:
        blocks = self.analyzer.enrich(blocks, source)
        blocks = self.planner.plan(blocks, source)
        return self.chunker.split(blocks)


ingestion_service = IngestionService()
