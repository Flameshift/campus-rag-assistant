"""父子分组与父窗口选择测试。"""

import unittest

from langchain_core.documents import Document

from app.parenting import (
    assign_parent_metadata,
    select_parent_window,
    should_expand_neighbors,
)


def make_document(
    index: int,
    content: str,
    strategy: str = "section",
    parent_key: str = "section-a",
    source: str = "rules.md",
) -> Document:
    return Document(
        page_content=content,
        metadata={
            "chunk_id": index + 1,
            "order_index": index,
            "source": source,
            "parent_key": parent_key,
            "chunk_strategy": strategy,
        },
    )


class ParentingTests(unittest.TestCase):
    def test_fixed_window_splits_large_section_parents(self):
        documents = [
            make_document(index, "内容" * 40)
            for index in range(5)
        ]

        assign_parent_metadata(documents, target_chars=120, max_children=3)

        parent_ids = {document.metadata["parent_id"] for document in documents}
        self.assertGreater(len(parent_ids), 1)
        self.assertTrue(all(document.metadata["parent_type"] == "section" for document in documents))

    def test_record_groups_share_format_scope(self):
        documents = [
            make_document(index, f"姓名: 学生{index}", strategy="record", parent_key="root")
            for index in range(6)
        ]

        assign_parent_metadata(documents, target_chars=1000, max_children=2)

        parent_ids = [document.metadata["parent_id"] for document in documents]
        self.assertEqual(3, len(set(parent_ids)))
        self.assertEqual([0, 1, 0, 1, 0, 1], [document.metadata["parent_order_index"] for document in documents])
        self.assertTrue(all(document.metadata["parent_type"] == "record_group" for document in documents))

    def test_select_parent_window_keeps_anchor_and_nearby_children(self):
        documents = [
            make_document(index, f"第{index}段")
            for index in range(6)
        ]
        assign_parent_metadata(documents, target_chars=1000, max_children=6)

        window = select_parent_window(
            documents,
            documents[3],
            max_chars=1000,
            max_children=3,
        )

        self.assertEqual([2, 3, 4], [item.metadata["order_index"] for item in window])

    def test_parent_expansion_suppresses_neighbor_fallback(self):
        document = make_document(0, "已经通过父级扩展补齐")
        document.metadata["parent_expansion_applied"] = True

        self.assertFalse(should_expand_neighbors(document, conditional=True))
        self.assertTrue(should_expand_neighbors(document, conditional=False))

    def test_parent_expanded_candidate_suppresses_neighbor_fallback(self):
        document = make_document(0, "由父级扩展带出的兄弟块")
        document.metadata["expanded_parent"] = True

        self.assertFalse(should_expand_neighbors(document, conditional=True))

    def test_neighbor_fallback_runs_when_parent_expansion_is_unavailable(self):
        document = make_document(0, "没有父级扩展结果")

        self.assertTrue(should_expand_neighbors(document, conditional=True))


if __name__ == "__main__":
    unittest.main()
