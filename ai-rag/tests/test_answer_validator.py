"""回答数字校验和子问题覆盖测试。"""

import unittest

from langchain_core.documents import Document

from app.answer_validator import AnswerValidator


class AnswerValidatorTests(unittest.TestCase):
    def setUp(self):
        self.validator = AnswerValidator()

    def test_detects_number_bound_to_wrong_object(self):
        documents = [
            Document(
                page_content="德育（F1）考核总分满分30分。",
                metadata={"chunk_id": 1},
            ),
            Document(
                page_content="综合素质评价总分满分100分。",
                metadata={"chunk_id": 2},
            ),
        ]

        report = self.validator.validate_numeric_consistency(
            "德育（F1）考核总分满分100分。",
            documents,
        )

        self.assertEqual(1, report["conflict_count"])
        conflict = report["conflicts"][0]
        self.assertEqual("100", conflict["answer"]["value"])
        self.assertEqual("30", conflict["evidence"]["value"])

    def test_supports_number_with_matching_object(self):
        documents = [
            Document(
                page_content="国家奖学金奖励标准为每人每年8000元。",
                metadata={"chunk_id": 1},
            )
        ]

        report = self.validator.validate_numeric_consistency(
            "国家奖学金每人每年8000元。",
            documents,
        )

        self.assertEqual(0, report["conflict_count"])
        self.assertEqual(1.0, report["supported_rate"])

    def test_builds_subquestion_coverage_matrix(self):
        documents = [
            Document(page_content="学校体育考查机制的总体目标包括完善考查制度。"),
            Document(page_content="家庭经济困难学生资助目的是激励勤奋学习和全面发展。"),
        ]

        coverage = self.validator.build_coverage(
            [
                "学校体育考查机制的总体目标是什么？",
                "家庭经济困难学生资助办法的目的是什么？",
            ],
            documents,
        )

        self.assertEqual(2, coverage["subquestion_count"])
        self.assertEqual(2, coverage["covered_count"])
        self.assertEqual(1.0, coverage["coverage_rate"])


if __name__ == "__main__":
    unittest.main()
