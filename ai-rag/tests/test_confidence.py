"""综合置信度的轻量测试。"""

import unittest

from langchain_core.documents import Document

from app.confidence import ConfidenceEvaluator


class ConfidenceTests(unittest.TestCase):
    def setUp(self):
        self.evaluator = ConfidenceEvaluator()

    def test_high_confidence_grounded_answer(self):
        documents = [
            Document(
                page_content="学生认为成绩有误，可在下一学期开学后5个工作日内向学院办公室申请复查。",
                metadata={
                    "rerank_score": 0.96,
                    "parent_key": "clause-25",
                    "source": "handbook.pdf",
                },
            ),
            Document(
                page_content="课程考核成绩由期末考试成绩和平时成绩组成。",
                metadata={
                    "rerank_score": 0.70,
                    "parent_key": "clause-25",
                    "source": "handbook.pdf",
                },
            ),
        ]
        answer = "学生可在下一学期开学后5个工作日内向学院办公室申请复查。[证据1]"

        result = self.evaluator.evaluate("成绩有误多久内找谁复查？", answer, documents)

        self.assertGreater(result.overall, 0.7)
        self.assertEqual("answer", result.action)

    def test_low_confidence_without_evidence(self):
        result = self.evaluator.evaluate("学校食堂几点关门？", "食堂晚上十点关门。", [])

        self.assertLess(result.overall, 0.5)
        self.assertIn(result.action, {"retrieve_again", "clarify_or_refuse"})

    def test_no_info_conflict_adds_risk(self):
        documents = [
            Document(
                page_content="学生认为成绩有误，可在下一学期开学后5个工作日内向学院办公室申请复查。",
                metadata={"rerank_score": 0.96, "parent_key": "clause-25"},
            )
        ]
        result = self.evaluator.evaluate(
            "成绩有误多久内找谁？",
            "资料中未提供成绩复核信息。[证据1]",
            documents,
            rewrite={"used_history": True, "slots": {"topic": "成绩复查"}},
        )

        self.assertGreater(result.risk_penalty, 0.0)

    def test_fallback_applicability_adds_risk_and_serializes(self):
        documents = [
            Document(
                page_content="专业必修课考核不及格必须重修。",
                metadata={"rerank_score": 0.95, "parent_key": "clause-19"},
            )
        ]

        result = self.evaluator.evaluate(
            "我是26级新生，挂科后怎么办？",
            "专业必修课考核不及格必须重修。[证据1]",
            documents,
            applicability_scope={"applicability_mode": "fallback"},
        )

        self.assertGreater(result.signals["applicability_risk"], 0.0)
        self.assertEqual("answer_with_fallback", result.action)
        self.assertIsInstance(result.to_dict()["signals"]["applicability_risk"], float)

    def test_latest_current_applicability_uses_notice_action(self):
        documents = [
            Document(
                page_content="专业必修课考核不及格必须重修。",
                metadata={"rerank_score": 0.95, "parent_key": "clause-19"},
            )
        ]

        result = self.evaluator.evaluate(
            "挂科后怎么办？",
            "专业必修课考核不及格必须重修。[证据1]",
            documents,
            applicability_scope={"applicability_mode": "latest_current"},
        )

        self.assertEqual("answer_with_applicability_notice", result.action)


if __name__ == "__main__":
    unittest.main()
