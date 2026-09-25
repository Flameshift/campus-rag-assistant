"""回答约束提示词的轻量测试。"""

import unittest

from langchain_core.documents import Document

from app.citations import (
    append_source_footer,
    build_evidence_context,
    build_new_source_footer,
)
from app.prompts import RAG_SYSTEM_PROMPT
from app.query_rewriter import QueryRewriter, REWRITE_SYSTEM_PROMPT


class PromptTests(unittest.TestCase):
    def test_prompt_limits_answer_scope(self):
        self.assertIn("只使用这些直接相关条款回答", RAG_SYSTEM_PROMPT)
        self.assertIn("必须完整列出构成结论所必需的条件", RAG_SYSTEM_PROMPT)
        self.assertIn("不能把可选条件写成强制条件", RAG_SYSTEM_PROMPT)
        self.assertIn("不补充参考资料中没有出现的日期", RAG_SYSTEM_PROMPT)
        self.assertIn("[证据1]", RAG_SYSTEM_PROMPT)
        self.assertIn("如果任何证据直接对应检索意图", RAG_SYSTEM_PROMPT)
        self.assertIn("覆盖与用户问题直接相关的完整类别边界", RAG_SYSTEM_PROMPT)
        self.assertIn("问题包含多个子问题", RAG_SYSTEM_PROMPT)
        self.assertIn("不能把一个对象或分项的数值移植到另一个对象或分项", RAG_SYSTEM_PROMPT)
        self.assertIn("优先使用正文印刷页码", RAG_SYSTEM_PROMPT)
        self.assertIn("必须先明确核心对象的总量", RAG_SYSTEM_PROMPT)

    def test_prompt_keeps_context_placeholder(self):
        self.assertIn("{context}", RAG_SYSTEM_PROMPT)

    def test_source_footer_uses_metadata(self):
        documents = [
            Document(
                page_content="测试内容",
                metadata={
                    "source": "学生手册.pdf",
                    "document_title": "陕西师范大学学生管理规定",
                    "document_number": "陕师校发〔2024〕1号",
                    "version": 2,
                    "is_current": True,
                    "effective_date": "2024-09-01",
                    "applicability": "全日制本科生",
                    "page_start": 10,
                    "page_end": 11,
                    "section_path": "第一章 > 第二条",
                },
            )
        ]

        context = build_evidence_context(documents)
        answer = append_source_footer("回答内容", documents)

        self.assertIn("[证据1]", context)
        self.assertIn("学生手册.pdf", context)
        self.assertIn("陕西师范大学学生管理规定", context)
        self.assertIn("文件号：陕师校发〔2024〕1号", context)
        self.assertIn("生效日期：2024-09-01", context)
        self.assertIn("适用范围：全日制本科生", context)
        self.assertIn("**信息来源**", answer)
        self.assertIn("第 10-11 页", answer)
        self.assertIn("第一章 > 第二条", answer)

    def test_source_footer_only_lists_cited_evidence(self):
        documents = [
            Document(page_content="一", metadata={"source": "a.pdf", "page": 1}),
            Document(page_content="二", metadata={"source": "b.pdf", "page": 2}),
        ]

        answer = append_source_footer("回答 [证据2]", documents)

        self.assertNotIn("a.pdf", answer)
        self.assertIn("b.pdf", answer)

    def test_stream_footer_contains_only_the_new_footer(self):
        documents = [
            Document(page_content="一", metadata={"source": "a.pdf", "page": 1}),
        ]
        answer = "回答内容 [证据1]"

        footer = build_new_source_footer(answer, documents)

        self.assertIn("**信息来源**", footer)
        self.assertNotIn(answer, footer)
        self.assertEqual(
            "",
            build_new_source_footer("回答内容\n**信息来源**", documents),
        )

    def test_query_rewriter_detects_ambiguous_follow_up(self):
        rewriter = QueryRewriter()
        history = [{"role": "user", "content": "我这一学期累计旷课已经超过10学时了。"}]

        self.assertTrue(rewriter.should_rewrite("这个严重吗？学校会怎么处理？", history))
        fallback = rewriter._fallback("这个严重吗？", history)

        self.assertIn("旷课", fallback["query"])
        self.assertIn("这个严重吗", fallback["query"])

    def test_query_rewriter_limits_lexical_drift(self):
        self.assertIn("只做消歧所需的最小改写", REWRITE_SYSTEM_PROMPT)
        self.assertIn("不能把问题扩大到相近但不同的业务类别", REWRITE_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
