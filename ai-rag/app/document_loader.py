# 文档加载兼容入口：保留原函数名，内部统一走结构化摄取流程。

from langchain_core.documents import Document

from .ingestion.service import ingestion_service


def load_documents_from_file(filename: str, content: bytes) -> list[Document]:
    """解析并完成分块，返回可以直接写入向量库的 Document。"""
    return ingestion_service.load_and_split(filename, content)
