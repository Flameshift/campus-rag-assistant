"""检索证据编号与回答来源列表的格式化工具。"""

import re

from langchain_core.documents import Document


def _page_text(metadata: dict) -> str:
    start = metadata.get("page_start", metadata.get("page"))
    end = metadata.get("page_end", start)
    if start is None:
        return ""
    if end is not None and end != start:
        return f"第 {start}-{end} 页"
    return f"第 {start} 页"


def _short_section_path(value: str) -> str:
    """Trim long PDF-derived headings so source labels do not show cut-off sentences."""
    parts = [part.strip() for part in str(value or "").split(">") if part.strip()]
    shortened = []
    for part in parts:
        part = re.split(r"[，,。！？；;]", part, maxsplit=1)[0].strip()
        if len(part) > 32:
            part = f"{part[:32].rstrip()}…"
        shortened.append(part)
    return " > ".join(shortened)


def format_evidence_header(index: int, metadata: dict) -> str:
    """生成放入 Prompt 的证据编号和来源说明。"""
    source = str(
        metadata.get("document_title")
        or metadata.get("source")
        or "未知文档"
    )
    label = f"[证据{index}] {source}"
    source_file = str(metadata.get("source") or "").strip()
    if source_file and source_file != source:
        label += f"（文件：{source_file}）"
    document_number = str(metadata.get("document_number") or "").strip()
    if document_number:
        label += f"，文件号：{document_number}"
    version = metadata.get("version")
    if version not in (None, ""):
        status = "现行" if bool(metadata.get("is_current")) else str(
            metadata.get("version_status") or "历史版本"
        )
        label += f"，版本：v{version}（{status}）"
    effective_date = str(metadata.get("effective_date") or "").strip()
    if effective_date:
        label += f"，生效日期：{effective_date}"
    applicability = str(metadata.get("applicability") or "").strip()
    if applicability:
        label += f"，适用范围：{applicability}"
    page = _page_text(metadata)
    if page:
        label += f"，{page}"
    section_path = str(metadata.get("section_path") or "").strip()
    if section_path:
        label += f"，章节：{_short_section_path(section_path)}"
    return label


def build_evidence_context(documents: list[Document]) -> str:
    """把检索分块拼成带证据编号的模型上下文。"""
    return "\n\n".join(
        f"{format_evidence_header(index, document.metadata)}\n{document.page_content}"
        for index, document in enumerate(documents, start=1)
    )


def build_source_footer(
    documents: list[Document],
    cited_indices: set[int] | None = None,
) -> str:
    """根据分块 metadata 生成稳定、可核对的回答来源列表。"""
    if not documents:
        return ""

    lines = ["", "---", "**信息来源**"]
    for index, document in enumerate(documents, start=1):
        if cited_indices and index not in cited_indices:
            continue
        lines.append(f"- {format_evidence_header(index, document.metadata)}")
    if len(lines) == 3:
        return ""
    return "\n".join(lines)


def append_source_footer(answer: str, documents: list[Document]) -> str:
    """避免重复追加来源列表。"""
    footer = build_new_source_footer(answer, documents)
    if not footer:
        return answer
    return answer.rstrip() + footer


def build_new_source_footer(answer: str, documents: list[Document]) -> str:
    """Return only the footer that still needs to be appended."""
    if "**信息来源**" in answer:
        return ""
    cited_indices = {
        int(match)
        for match in re.findall(r"\[\s*证据\s*(\d+)\s*\]", answer)
    }
    return build_source_footer(documents, cited_indices or None)
