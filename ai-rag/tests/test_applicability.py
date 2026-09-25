"""Applicability and cohort source-selection tests."""

import unittest

from app.applicability import (
    cohort_matches,
    extract_cohorts,
    is_general_applicability,
)
from app.retrieval_scope import select_applicability_sources


def source_row(
    source_id: int,
    applicability: str,
    *,
    version: int = 1,
    current: bool = True,
    effective_date: str | None = None,
    title: str = "学生手册",
) -> tuple:
    return (
        source_id,
        f"doc-{source_id}",
        version,
        effective_date,
        current,
        applicability,
        title,
        title,
    )


class ApplicabilityTests(unittest.TestCase):
    def test_extracts_cohort_from_arabic_and_short_forms(self):
        self.assertEqual({2024}, extract_cohorts("2024级本科生"))
        self.assertEqual({2026}, extract_cohorts("26级本科生"))
        self.assertEqual({2026}, extract_cohorts("26级和2026级"))

    def test_general_applicability_requires_no_specific_cohort(self):
        self.assertTrue(is_general_applicability("全日制本科生"))
        self.assertFalse(is_general_applicability("2024级本科生"))

    def test_exact_cohort_prefers_matching_file(self):
        rows = [
            source_row(1, "2024级本科生"),
            source_row(2, "2026级本科生"),
        ]

        selection = select_applicability_sources(rows, {1, 2}, "2024")

        self.assertEqual("exact", selection.mode)
        self.assertEqual({1}, set(selection.source_ids))
        self.assertTrue(cohort_matches(selection.applicability, 2024))

    def test_missing_cohort_uses_fallback_file(self):
        rows = [source_row(1, "2024级本科生")]

        selection = select_applicability_sources(rows, {1}, "2026")

        self.assertEqual("fallback", selection.mode)
        self.assertEqual({1}, set(selection.source_ids))

    def test_unspecified_cohort_uses_latest_current_with_marker(self):
        rows = [source_row(1, "2024级本科生")]

        selection = select_applicability_sources(rows, {1}, "")

        self.assertEqual("latest_current", selection.mode)
        self.assertEqual({1}, set(selection.source_ids))

    def test_general_file_is_preferred_when_no_cohort_is_given(self):
        rows = [
            source_row(1, "2024级本科生"),
            source_row(2, "全日制本科生"),
        ]

        selection = select_applicability_sources(rows, {1, 2}, "")

        self.assertEqual("general", selection.mode)
        self.assertEqual({2}, set(selection.source_ids))


if __name__ == "__main__":
    unittest.main()
