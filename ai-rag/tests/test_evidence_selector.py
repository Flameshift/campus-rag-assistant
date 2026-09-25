"""证据标题加权测试。"""

import unittest

from langchain_core.documents import Document

from app.evidence_selector import boost_quoted_title_matches


class EvidenceSelectorTests(unittest.TestCase):
    def test_exact_quoted_title_gets_boost(self):
        wrong = Document(
            page_content="原《陕西师范大学学生考试违纪、作弊处理办法》同时废止。",
            metadata={"rerank_score": 0.95},
        )
        right = Document(
            page_content="原《陕西师范大学学生\n违纪处分规定》同时废止。",
            metadata={"rerank_score": 0.90},
        )

        ranked = boost_quoted_title_matches(
            [wrong, right],
            "根据《陕西师范大学学生违纪处分规定》，原哪份文件废止？",
        )

        self.assertIs(ranked[0], right)
        self.assertTrue(right.metadata["exact_title_match"])


if __name__ == "__main__":
    unittest.main()
