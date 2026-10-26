"""RAG 组件之间共享的类型契约。"""

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document


@dataclass(slots=True)
class PreparedChat:
    """一次问答在生成阶段之前需要的全部检索结果。"""

    docs: list[Document]
    sources: list[dict[str, Any]]
    timings: dict[str, float]
    rewrite: dict[str, Any]
    query_plan: dict[str, Any]
    retrieval_scope: dict[str, Any]
    applicability_notice: str
    coverage: dict[str, Any]
    input_data: dict[str, Any]
    clarification: str | None = None
