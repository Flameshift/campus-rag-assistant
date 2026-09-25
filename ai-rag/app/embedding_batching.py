"""Bounded batch and concurrent embedding execution."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from langchain_core.embeddings import Embeddings


class BoundedBatchEmbeddings(Embeddings):
    """Batch texts and run a bounded number of embedding requests concurrently."""

    def __init__(
        self,
        delegate: Embeddings,
        *,
        batch_size: int,
        max_concurrency: int,
    ) -> None:
        self.delegate = delegate
        self.batch_size = max(1, int(batch_size))
        self.max_concurrency = max(1, int(max_concurrency))

    def _batches(self, texts: list[str]) -> list[list[str]]:
        return [
            texts[index : index + self.batch_size]
            for index in range(0, len(texts), self.batch_size)
        ]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        batches = self._batches(texts)
        if len(batches) == 1 or self.max_concurrency == 1:
            return [
                vector
                for batch in batches
                for vector in self.delegate.embed_documents(batch)
            ]

        worker_count = min(self.max_concurrency, len(batches))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            batch_vectors = list(
                executor.map(self.delegate.embed_documents, batches)
            )
        return [vector for vectors in batch_vectors for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.delegate.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        batches = self._batches(texts)
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def embed_batch(batch: list[str]) -> list[list[float]]:
            async with semaphore:
                async_embed = getattr(self.delegate, "aembed_documents", None)
                if async_embed is not None:
                    return await async_embed(batch)
                return await asyncio.to_thread(
                    self.delegate.embed_documents,
                    batch,
                )

        batch_vectors = await asyncio.gather(
            *(embed_batch(batch) for batch in batches)
        )
        return [vector for vectors in batch_vectors for vector in vectors]

    async def aembed_query(self, text: str) -> list[float]:
        async_embed = getattr(self.delegate, "aembed_query", None)
        if async_embed is not None:
            return await async_embed(text)
        return await asyncio.to_thread(self.delegate.embed_query, text)
