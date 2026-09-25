"""父级分组与父上下文窗口选择。

子块负责精确检索；父级只提供完整条款、表格或记录组上下文。
有结构时按结构分组，无结构时按固定大小窗口兜底。
"""

import hashlib

from langchain_core.documents import Document


def _document_key(document: Document) -> str:
    metadata = document.metadata
    return str(
        metadata.get("chunk_id")
        or metadata.get("content_hash")
        or metadata.get("logical_hash")
        or document.page_content
    )


def parent_scope(metadata: dict) -> tuple[str, str]:
    """返回父级分组键和父级类型。"""
    source = str(metadata.get("source") or "")
    semantic_key = str(metadata.get("parent_key") or "")
    strategy = str(metadata.get("chunk_strategy") or metadata.get("block_type") or "")

    if strategy == "table":
        parent_type = "table"
        discriminator = str(
            metadata.get("sheet_name")
            or metadata.get("table_id")
            or semantic_key
        )
    elif strategy == "record":
        parent_type = "record_group"
        discriminator = str(
            metadata.get("record_collection")
            or metadata.get("record_type")
            or semantic_key
        )
    elif strategy == "code":
        parent_type = "code"
        discriminator = semantic_key
    elif strategy == "section":
        parent_type = "section"
        discriminator = semantic_key
    else:
        parent_type = "fixed_window"
        discriminator = semantic_key

    raw = "|".join((source, parent_type, discriminator))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24], parent_type


def assign_parent_metadata(
    documents: list[Document],
    target_chars: int,
    max_children: int,
) -> list[Document]:
    """为子块分配结构感知或固定窗口父级。"""
    if not documents:
        return documents

    groups: list[list[Document]] = []
    current: list[Document] = []
    current_scope = ""
    current_type = ""
    current_size = 0

    def flush() -> None:
        nonlocal current, current_scope, current_type, current_size
        if current:
            groups.append(current)
        current = []
        current_scope = ""
        current_type = ""
        current_size = 0

    for document in documents:
        scope_key, parent_type = parent_scope(document.metadata)
        content_size = len(document.page_content)
        same_scope = scope_key == current_scope and parent_type == current_type
        exceeds = current and (
            current_size + content_size > target_chars
            or len(current) >= max_children
        )
        if current and (not same_scope or exceeds):
            flush()
        if not current:
            current_scope = scope_key
            current_type = parent_type
        current.append(document)
        current_size += content_size

    flush()

    for group_index, group in enumerate(groups):
        start = group[0].metadata.get("order_index")
        end = group[-1].metadata.get("order_index")
        source = str(group[0].metadata.get("source") or "")
        parent_id = hashlib.sha256(
            f"{source}|{_group_type(group[0])}|{group_index}|{start}|{end}|v1".encode("utf-8")
        ).hexdigest()[:32]
        for index, document in enumerate(group):
            document.metadata["parent_id"] = parent_id
            document.metadata["parent_type"] = _group_type(group[0])
            document.metadata["parent_order_index"] = index
            document.metadata["parent_child_count"] = len(group)
            document.metadata["parent_version"] = "v1"

    return documents


def _group_type(document: Document) -> str:
    return parent_scope(document.metadata)[1]


def select_parent_window(
    documents: list[Document],
    anchor: Document,
    max_chars: int,
    max_children: int,
) -> list[Document]:
    """从父级文档中选择锚点附近的有界窗口。"""
    if not documents:
        return []

    ordered = sorted(
        documents,
        key=lambda item: (
            int(item.metadata.get("order_index", 0) or 0),
            int(item.metadata.get("parent_order_index", 0) or 0),
        ),
    )
    anchor_key = _document_key(anchor)
    anchor_index = next(
        (index for index, item in enumerate(ordered) if _document_key(item) == anchor_key),
        0,
    )

    selected = [ordered[anchor_index]]
    selected_keys = {anchor_key}
    used_chars = len(ordered[anchor_index].page_content)
    left = anchor_index - 1
    right = anchor_index + 1

    while left >= 0 or right < len(ordered):
        candidates = []
        if right < len(ordered):
            candidates.append((right, right - anchor_index))
        if left >= 0:
            candidates.append((left, anchor_index - left))

        index, _ = min(candidates, key=lambda item: item[1])
        candidate = ordered[index]
        candidate_size = len(candidate.page_content)
        candidate_key = _document_key(candidate)

        if (
            len(selected) >= max_children
            or used_chars + candidate_size > max_chars
        ):
            break
        if candidate_key not in selected_keys:
            selected.append(candidate)
            selected_keys.add(candidate_key)
            used_chars += candidate_size

        if index == left:
            left -= 1
        else:
            right += 1

    selected.sort(
        key=lambda item: (
            int(item.metadata.get("order_index", 0) or 0),
            int(item.metadata.get("parent_order_index", 0) or 0),
        )
    )
    return selected


def should_expand_neighbors(
    document: Document,
    *,
    conditional: bool = True,
) -> bool:
    """Return whether a hit should receive neighbor fallback expansion."""
    if not conditional:
        return True
    return not bool(
        document.metadata.get("parent_expansion_applied")
        or document.metadata.get("expanded_parent")
    )
