"""Multi-query rank fusion tests."""

import unittest

from langchain_core.documents import Document

from app.retrieval_fusion import reciprocal_rank_fusion


class RetrievalFusionTests(unittest.TestCase):
    def test_rrf_deduplicates_and_prioritizes_multi_query_agreement(self):
        first = Document(page_content="一", metadata={"chunk_id": 1})
        shared = Document(page_content="共同证据", metadata={"chunk_id": 2})
        third = Document(page_content="三", metadata={"chunk_id": 3})

        fused = reciprocal_rank_fusion(
            [[first, shared], [shared, third]],
            rrf_k=60,
        )

        self.assertEqual(3, len(fused))
        self.assertEqual(2, fused[0].metadata["chunk_id"])
        self.assertGreater(fused[0].metadata["rrf_score"], fused[1].metadata["rrf_score"])

    def test_empty_result_sets_return_empty_list(self):
        self.assertEqual([], reciprocal_rank_fusion([]))


if __name__ == "__main__":
    unittest.main()
