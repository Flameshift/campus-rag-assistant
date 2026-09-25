"""Bounded embedding batch execution tests."""

import unittest

from langchain_core.embeddings import Embeddings

from app.embedding_batching import BoundedBatchEmbeddings


class RecordingEmbeddings(Embeddings):
    def __init__(self) -> None:
        self.batches: list[tuple[str, ...]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(tuple(texts))
        return [[float(len(text))] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text))]


class EmbeddingBatchingTests(unittest.TestCase):
    def test_embed_documents_preserves_order_across_batches(self):
        delegate = RecordingEmbeddings()
        embeddings = BoundedBatchEmbeddings(
            delegate,
            batch_size=2,
            max_concurrency=2,
        )

        vectors = embeddings.embed_documents(["a", "bb", "ccc", "dddd", "eeeee"])

        self.assertEqual([[1.0], [2.0], [3.0], [4.0], [5.0]], vectors)
        self.assertEqual(3, len(delegate.batches))
        self.assertEqual([1, 2, 2], sorted(len(batch) for batch in delegate.batches))

    def test_embed_documents_uses_one_batch_when_within_limit(self):
        delegate = RecordingEmbeddings()
        embeddings = BoundedBatchEmbeddings(
            delegate,
            batch_size=25,
            max_concurrency=3,
        )

        embeddings.embed_documents(["a", "b", "c"])

        self.assertEqual(1, len(delegate.batches))
        self.assertEqual(("a", "b", "c"), delegate.batches[0])


class AsyncEmbeddingBatchingTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_embedding_preserves_order(self):
        delegate = RecordingEmbeddings()
        embeddings = BoundedBatchEmbeddings(
            delegate,
            batch_size=2,
            max_concurrency=2,
        )

        vectors = await embeddings.aembed_documents(["a", "bb", "ccc"])

        self.assertEqual([[1.0], [2.0], [3.0]], vectors)


if __name__ == "__main__":
    unittest.main()
