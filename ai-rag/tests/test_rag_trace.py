"""RAG Trace 轻量测试。"""

import unittest

from app.rag_trace import estimate_tokens


class RagTraceTests(unittest.TestCase):
    def test_estimates_chinese_and_ascii_tokens(self):
        self.assertEqual(6, estimate_tokens("学生手册 AIGC 2024"))


if __name__ == "__main__":
    unittest.main()
