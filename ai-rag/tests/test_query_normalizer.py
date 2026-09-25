"""Query normalization and rewrite rule tests."""

import unittest
from unittest.mock import patch

from app.query_normalizer import normalize_query
from app.query_rewriter import QueryRewriter


class QueryNormalizerTests(unittest.TestCase):
    def test_normalizes_colloquial_alias(self):
        result = normalize_query("我想问一下，挂科了咋办？")

        self.assertIn("考核不合格", result["query"])
        self.assertNotIn("我想问一下", result["query"])
        self.assertTrue(result["changes"])

    def test_appends_arabic_number_equivalent(self):
        result = normalize_query("旷课十学时会被处分吗？")

        self.assertIn("10学时", result["query"])
        self.assertIn("十学时", result["query"])

    def test_rewrite_keeps_number_and_quoted_title(self):
        self.assertTrue(
            QueryRewriter._preserves_constraints(
                "《学生管理规定》超过10学时的处理方式是什么？",
                "《学生管理规定》超过10学时应如何处理？",
            )
        )
        self.assertFalse(
            QueryRewriter._preserves_constraints(
                "《学生管理规定》超过10学时的处理方式是什么？",
                "学生管理规定中旷课应如何处理？",
            )
        )

    def test_rewrite_uses_rules_when_llm_is_disabled(self):
        rewriter = QueryRewriter()

        with patch("app.query_rewriter.config.LLM_API_KEY", ""):
            result = rewriter.rewrite("挂科了咋办？", [])

        self.assertIn("考核不合格", result["query"])
        self.assertFalse(result["used_history"])
        self.assertEqual("normalize", result["rewrite_type"])

    def test_long_standalone_question_is_routed_to_rewrite(self):
        rewriter = QueryRewriter()
        question = "我现在遇到一个很复杂的情况，" + "需要补充很多背景信息，" * 20

        with patch("app.query_rewriter.config.LLM_API_KEY", "test-key"):
            self.assertTrue(rewriter.should_rewrite(question, []))


if __name__ == "__main__":
    unittest.main()
