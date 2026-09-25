"""Rank fusion utilities for multi-query retrieval."""

from __future__ import annotations

from collections import OrderedDict
from typing import Iterable

from langchain_core.documents import Document


def document_identity(document: Document) -> str:
    """Return the same stable identity used by retrieval deduplication."""
    metadata = document.metadata or {}
    return str(
        metadata.get("chunk_id")
        or metadata.get("content_hash")
        or metadata.get("logical_hash")
        or document.page_content
    )


def reciprocal_rank_fusion(
    result_sets: Iterable[list[Document]],
    *,
    rrf_k: int = 60,
    weights: list[float] | None = None,
    limit: int | None = None,
) -> list[Document]:
    """Merge ranked result lists with weighted Reciprocal Rank Fusion.

    RRF combines ranks instead of raw retrieval scores, so BM25 and vector
    scores do not need to share a scale. Duplicate chunks are merged while
    retaining the first document object and its metadata.
    """
    result_lists = [list(items) for items in result_sets]
    if not result_lists:
        return []

    if weights is None:
        weights = [1.0] * len(result_lists)
    if len(weights) != len(result_lists):
        raise ValueError("weights must match the number of result sets")

    scores: dict[str, float] = {}
    first_rank: dict[str, int] = {}
    documents: OrderedDict[str, Document] = OrderedDict()

    for result_index, documents_in_set in enumerate(result_lists):
        weight = float(weights[result_index])
        for rank, document in enumerate(documents_in_set, start=1):
            key = document_identity(document)
            documents.setdefault(key, document)
            scores[key] = scores.get(key, 0.0) + weight / (rrf_k + rank)
            first_rank.setdefault(key, rank)

    ordering = sorted(
        documents,
        key=lambda key: (-scores[key], first_rank[key], key),
    )
    if limit is not None:
        ordering = ordering[: max(0, limit)]

    fused: list[Document] = []
    for key in ordering:
        document = documents[key]
        metadata = dict(document.metadata or {})
        metadata["rrf_score"] = round(scores[key], 8)
        fused.append(Document(page_content=document.page_content, metadata=metadata))
    return fused
