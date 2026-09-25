"""把相邻子块合并成可引用、可追溯的 Evidence Object。"""

import hashlib
import re
from collections import OrderedDict

from langchain_core.documents import Document

from . import config


SECTION_PREFIX_PATTERN = re.compile(r"^【章节】[^\n]*\n+")


def build_evidence_objects(documents: list[Document]) -> list[Document]:
    if not config.EVIDENCE_OBJECT_ENABLED or not documents:
        return documents

    ordered = []
    seen_chunks = set()
    for position, document in enumerate(documents):
        key = _chunk_key(document)
        if key in seen_chunks:
            continue
        seen_chunks.add(key)
        ordered.append((position, document))

    grouped: OrderedDict[tuple, list[tuple[int, Document]]] = OrderedDict()
    for position, document in ordered:
        grouped.setdefault(_object_key(document), []).append((position, document))

    evidence_objects: list[tuple[float, int, Document]] = []
    for group_key, items in grouped.items():
        for segment in _contiguous_segments(items):
            evidence = _merge_segment(group_key, segment)
            score = max(
                float(document.metadata.get("rerank_score", 0.0) or 0.0)
                for _, document in segment
            )
            position = min(position for position, _ in segment)
            evidence_objects.append((score, position, evidence))

    evidence_objects.sort(key=lambda item: (-item[0], item[1]))
    return [document for _, _, document in evidence_objects]


def _chunk_key(document: Document) -> str:
    return str(
        document.metadata.get("chunk_id")
        or document.metadata.get("content_hash")
        or document.page_content
    )


def _object_key(document: Document) -> tuple:
    metadata = document.metadata
    parent_identity = (
        metadata.get("parent_id")
        or metadata.get("parent_key")
        or metadata.get("chunk_id")
        or metadata.get("content_hash")
        or document.page_content
    )
    return (
        metadata.get("source_file_id"),
        metadata.get("version"),
        parent_identity,
    )


def _contiguous_segments(
    items: list[tuple[int, Document]],
) -> list[list[tuple[int, Document]]]:
    sorted_items = sorted(
        items,
        key=lambda item: (
            int(item[1].metadata.get("order_index", 0) or 0),
            item[0],
        ),
    )
    segments: list[list[tuple[int, Document]]] = []
    current: list[tuple[int, Document]] = []
    chars = 0
    for item in sorted_items:
        document = item[1]
        order_index = document.metadata.get("order_index")
        previous = current[-1][1] if current else None
        previous_order = previous.metadata.get("order_index") if previous else None
        contiguous = (
            previous is None
            or (
                isinstance(order_index, int)
                and isinstance(previous_order, int)
                and order_index - previous_order == 1
            )
        )
        current_chars = chars + len(document.page_content or "")
        if current and (
            not contiguous
            or len(current) >= config.EVIDENCE_OBJECT_MAX_CHILDREN
            or current_chars > config.EVIDENCE_OBJECT_MAX_CHARS
        ):
            segments.append(current)
            current = []
            chars = 0
        current.append(item)
        chars += len(document.page_content or "")
    if current:
        segments.append(current)
    return segments


def _merge_segment(
    group_key: tuple,
    segment: list[tuple[int, Document]],
) -> Document:
    first = segment[0][1]
    if len(segment) == 1:
        return first

    texts = [(document.page_content or "").strip() for _, document in segment]
    merged_text = texts[0]
    for text in texts[1:]:
        cleaned = SECTION_PREFIX_PATTERN.sub("", text)
        merged_text = _merge_overlapping_text(merged_text, cleaned)

    ranked_items = sorted(
        segment,
        key=lambda item: (
            -float(item[1].metadata.get("rerank_score", 0.0) or 0.0),
            int(item[1].metadata.get("order_index", 0) or 0),
        ),
    )
    chunk_ids = [
        document.metadata.get("chunk_id")
        for _, document in ranked_items
        if document.metadata.get("chunk_id") is not None
    ]
    rerank_scores = [
        float(document.metadata.get("rerank_score", 0.0) or 0.0)
        for _, document in segment
    ]
    page_starts = [
        int(document.metadata.get("page_start", document.metadata.get("page")))
        for _, document in segment
        if document.metadata.get("page_start", document.metadata.get("page")) is not None
    ]
    page_ends = [
        int(document.metadata.get("page_end", document.metadata.get("page")))
        for _, document in segment
        if document.metadata.get("page_end", document.metadata.get("page")) is not None
    ]
    evidence_id = hashlib.sha256(
        (
            "|".join(str(value) for value in group_key)
            + "|"
            + "|".join(str(value) for value in chunk_ids)
        ).encode("utf-8")
    ).hexdigest()[:16]

    metadata = dict(first.metadata)
    metadata.update(
        {
            "evidence_id": evidence_id,
            "evidence_object": True,
            "source_chunk_ids": chunk_ids,
            "merged_chunk_count": len(segment),
            "rerank_score": max(rerank_scores) if rerank_scores else 0.0,
            "expanded_parent": any(
                bool(document.metadata.get("expanded_parent"))
                for _, document in segment
            ),
            "expanded_neighbor": any(
                bool(document.metadata.get("expanded_neighbor"))
                for _, document in segment
            ),
            "coverage_fill": any(
                bool(document.metadata.get("coverage_fill"))
                for _, document in segment
            ),
        }
    )
    if page_starts:
        metadata["page_start"] = min(page_starts)
    if page_ends:
        metadata["page_end"] = max(page_ends)
    return Document(page_content=merged_text, metadata=metadata)


def _merge_overlapping_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    max_overlap = min(300, len(left), len(right))
    for size in range(max_overlap, 20, -1):
        if left[-size:] == right[:size]:
            return left + right[size:]
    return f"{left}\n{right}"
