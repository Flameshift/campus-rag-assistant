"""证据选择后的确定性加权规则。"""

import re

from langchain_core.documents import Document


QUOTED_TITLE_PATTERN = re.compile(r"《([^》]{2,80})》")
WHITESPACE_PATTERN = re.compile(r"\s+")


def _normalize_title_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub("", value)


def boost_quoted_title_matches(
    documents: list[Document],
    question: str,
    boost: float = 0.08,
) -> list[Document]:
    """问题明确引用文件标题时，提高正文精确命中该标题的证据。"""
    titles = {
        _normalize_title_text(title)
        for title in QUOTED_TITLE_PATTERN.findall(question)
        if _normalize_title_text(title)
    }
    if not titles:
        return documents

    for document in documents:
        searchable = _normalize_title_text(
            "\n".join(
            [
                document.page_content,
                str(document.metadata.get("document_title") or ""),
                str(document.metadata.get("section_path") or ""),
                str(document.metadata.get("document_aliases") or ""),
            ]
            )
        )
        matched = sorted(title for title in titles if title in searchable)
        if not matched:
            continue
        document.metadata["exact_title_match"] = True
        document.metadata["matched_document_titles"] = "|".join(matched)
        document.metadata["rerank_score"] = min(
            1.0,
            float(document.metadata.get("rerank_score", 0.0) or 0.0) + boost,
        )

    return sorted(
        documents,
        key=lambda document: float(
            document.metadata.get("rerank_score", 0.0) or 0.0
        ),
        reverse=True,
    )
