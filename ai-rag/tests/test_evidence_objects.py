"""Evidence Object 合并与条件扩展测试。"""

import unittest
from unittest.mock import patch

from langchain_core.documents import Document

from app.evidence_objects import build_evidence_objects


class EvidenceObjectTests(unittest.TestCase):
    def test_merges_contiguous_chunks_from_same_parent(self):
        documents = [
            Document(
                page_content="【章节】第一章\n\n第十二条 申请材料包括：",
                metadata={
                    "chunk_id": 1,
                    "source_file_id": 1,
                    "version": 1,
                    "parent_id": "p1",
                    "order_index": 10,
                    "rerank_score": 0.9,
                },
            ),
            Document(
                page_content="【章节】第一章\n\n身份证和成绩单。",
                metadata={
                    "chunk_id": 2,
                    "source_file_id": 1,
                    "version": 1,
                    "parent_id": "p1",
                    "order_index": 11,
                    "rerank_score": 0.8,
                },
            ),
        ]

        with patch("app.evidence_objects.config.EVIDENCE_OBJECT_ENABLED", True):
            merged = build_evidence_objects(documents)

        self.assertEqual(1, len(merged))
        self.assertEqual([1, 2], merged[0].metadata["source_chunk_ids"])
        self.assertEqual(1, merged[0].page_content.count("【章节】"))

    def test_does_not_merge_different_parents(self):
        documents = [
            Document(
                page_content="第一条 内容一。",
                metadata={
                    "chunk_id": 1,
                    "parent_id": "p1",
                    "order_index": 1,
                },
            ),
            Document(
                page_content="第二条 内容二。",
                metadata={
                    "chunk_id": 2,
                    "parent_id": "p2",
                    "order_index": 2,
                },
            ),
        ]

        with patch("app.evidence_objects.config.EVIDENCE_OBJECT_ENABLED", True):
            merged = build_evidence_objects(documents)

        self.assertEqual(2, len(merged))


if __name__ == "__main__":
    unittest.main()
