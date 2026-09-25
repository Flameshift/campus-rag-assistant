# Rerank 精排：对混合检索的候选分块做相关性重排。
#
# 当前默认使用阿里云百炼 qwen3.7-text-rerank；调用失败时自动回退原顺序，
# 保证主问答链路不被 Rerank 故障阻断。

import logging

import httpx
from langchain_core.documents import Document

from . import config

logger = logging.getLogger(__name__)


class Reranker:
    def __init__(self):
        self.enabled = config.RERANK_ENABLED and bool(config.RERANK_API_KEY)

    def rerank(self, question: str, documents: list[Document]) -> list[Document]:
        """按与问题的相关性重排候选文档。"""
        if not self.enabled or not documents:
            return documents

        payload = {
            "model": config.RERANK_MODEL,
            "input": {
                "query": question,
                "documents": [doc.page_content for doc in documents],
            },
            "parameters": {
                "return_documents": False,
                "top_n": len(documents),
            },
        }
        headers = {
            "Authorization": f"Bearer {config.RERANK_API_KEY}",
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(
                config.RERANK_BASE_URL,
                json=payload,
                headers=headers,
                timeout=config.RERANK_TIMEOUT,
            )
            response.raise_for_status()
            results = (response.json().get("output") or {}).get("results") or []

            ordered: list[Document] = []
            for item in results:
                index = item.get("index")
                score = item.get("relevance_score")
                if index is None or index < 0 or index >= len(documents):
                    continue
                document = documents[index]
                # 保留分数，便于评估和排查排序问题。
                document.metadata["rerank_score"] = score
                ordered.append(document)

            return ordered or documents
        except Exception as exc:
            logger.warning("Rerank 调用失败，已回退原检索顺序: %s", exc)
            return documents


reranker = Reranker()
