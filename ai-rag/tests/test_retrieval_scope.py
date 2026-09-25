"""Retrieval scope selection tests."""

import unittest

from app.retrieval_scope import RetrievalScope, select_source_ids


class RetrievalScopeTests(unittest.TestCase):
    def test_current_scope_uses_preselected_rows(self):
        rows = [(1, "doc-a", 2, "2025-01-01", True)]

        selected = select_source_ids(rows, "current", "")

        self.assertEqual({1}, selected)

    def test_as_of_scope_selects_latest_effective_version(self):
        rows = [
            (1, "doc-a", 1, "2024-01-01", False),
            (2, "doc-a", 2, "2025-01-01", True),
            (3, "doc-b", 1, "", False),
        ]

        selected = select_source_ids(rows, "as_of", "2024-06-01")

        self.assertEqual({1, 3}, selected)

    def test_scope_trace_summary_does_not_expose_row_objects(self):
        scope = RetrievalScope(
            allowed_source_ids=frozenset({3, 1}),
            time_intent="current",
        )

        payload = scope.to_trace_dict()

        self.assertEqual([1, 3], payload["allowed_source_ids"])
        self.assertEqual(2, payload["allowed_source_count"])


if __name__ == "__main__":
    unittest.main()
