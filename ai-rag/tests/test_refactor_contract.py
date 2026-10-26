"""重构后的公开入口与路由契约测试。"""

import unittest
from unittest.mock import patch

from langchain_core.documents import Document

from app.main import app
from app.rag.evidence import RagEvidence
from app.rag.pipeline import RagPipeline
from app.rag.retrieval import RagRetrieval
from app.rag.runtime import RagRuntime
from app.rag_service import RagService, StreamCancelled, rag_service


EXPECTED_ROUTES = {
    "/": {"get"},
    "/api/admin/documents": {"get"},
    "/api/admin/documents/{document_id}": {"delete"},
    "/api/admin/documents/{document_id}/activate-version": {"post"},
    "/api/admin/documents/{document_id}/disable": {"post"},
    "/api/admin/documents/{document_id}/reindex": {"post"},
    "/api/admin/documents/{document_id}/restore": {"post"},
    "/api/admin/documents/{document_id}/versions": {"get", "post"},
    "/api/admin/tasks": {"get"},
    "/api/chat": {"post"},
    "/api/chat/stream": {"post"},
    "/api/jobs/{upload_id}": {"get"},
    "/api/knowledge/count": {"get"},
    "/api/memory/{thread_id}": {"delete"},
    "/api/upload": {"post"},
    "/health": {"get"},
}

class RefactorContractTests(unittest.TestCase):
    def test_rag_service_uses_explicit_components(self):
        self.assertEqual(RagService.__mro__, (RagService, object))
        self.assertIsInstance(rag_service.runtime, RagRuntime)
        self.assertIsInstance(rag_service.evidence, RagEvidence)
        self.assertIsInstance(rag_service.retrieval, RagRetrieval)
        self.assertIsInstance(rag_service.pipeline, RagPipeline)
        self.assertIs(rag_service.evidence.runtime, rag_service.runtime)
        self.assertIs(rag_service.retrieval.runtime, rag_service.runtime)
        self.assertIs(rag_service.retrieval.evidence, rag_service.evidence)
        self.assertIs(rag_service.pipeline.runtime, rag_service.runtime)
        self.assertIs(rag_service.pipeline.retrieval, rag_service.retrieval)
        self.assertIsInstance(rag_service, RagService)
        self.assertTrue(issubclass(StreamCancelled, Exception))

    def test_rag_service_public_methods_delegate_to_components(self):
        documents = [Document(page_content="test", metadata={})]
        with patch.object(
            rag_service.runtime,
            "knowledge_count",
            return_value=7,
        ) as knowledge_count:
            self.assertEqual(rag_service.knowledge_count(), 7)
            knowledge_count.assert_called_once_with()

        with patch.object(
            rag_service.runtime,
            "add_documents",
            return_value=["chunk-1"],
        ) as add_documents:
            self.assertEqual(rag_service.add_documents(documents), ["chunk-1"])
            add_documents.assert_called_once_with(documents)

    def test_prompt_builder_resolves_evidence_context(self):
        prompt_input = RagRetrieval.build_prompt_input(
            {
                "docs": [],
                "question": "测试问题",
                "history": "",
                "retrieval_query": "测试问题",
            }
        )
        self.assertEqual(prompt_input["context"], "")

    def test_fastapi_route_contract_is_preserved(self):
        paths = app.openapi()["paths"]
        actual_routes = {
            path: {
                method
                for method in operations
                if method in {"get", "post", "put", "patch", "delete"}
            }
            for path, operations in paths.items()
        }
        self.assertEqual(actual_routes, EXPECTED_ROUTES)


if __name__ == "__main__":
    unittest.main()
