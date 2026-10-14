import math
from typing import Protocol

import httpx

from depscope.ingest.models import Contract
from depscope.runtime.errors import DomainError


class EmbeddingBatch(Contract):
    vectors: tuple[tuple[float, ...], ...]
    model_id: str
    model_digest: str
    usage: dict | None


class EmbeddingProvider(Protocol):
    async def embed(self, texts: tuple[str, ...]) -> EmbeddingBatch: ...


def validate_vector(vector, dimension):
    if (
        len(vector) != dimension
        or not dimension
        or any(
            isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v)
            for v in vector
        )
        or not any(v != 0 for v in vector)
    ):
        raise DomainError(
            "INVALID_VECTOR", "Embedding must be finite, nonzero and have the manifest dimension"
        )
    return tuple(float(v) for v in vector)


class OllamaEmbedding:
    def __init__(self, url, model, http=None):
        self.url, self.model, self.http = url.rstrip("/"), model, http

    async def embed(self, texts):
        if not texts or len(texts) > 64:
            raise DomainError("EMBEDDING_LIMIT", "Embedding batches require 1–64 texts")
        if self.http is None:
            async with httpx.AsyncClient(timeout=120, trust_env=False) as http:
                return await self._embed(texts, http)
        return await self._embed(texts, self.http)

    async def _embed(self, texts, http):
        try:
            before = await http.get(self.url + "/api/tags")
            before.raise_for_status()
            digest = next(m["digest"] for m in before.json()["models"] if m["name"] == self.model)
            response = await http.post(
                self.url + "/api/embed",
                json={
                    "model": self.model,
                    "input": list(texts),
                    "truncate": False,
                    "keep_alive": "10m",
                },
            )
            response.raise_for_status()
            value = response.json()
            after = await http.get(self.url + "/api/tags")
            after.raise_for_status()
            current = next(m["digest"] for m in after.json()["models"] if m["name"] == self.model)
            if current != digest or value.get("model") != self.model:
                raise DomainError(
                    "EMBEDDING_MODEL_CHANGED", "Embedding model changed during request"
                )
            vectors = value["embeddings"]
            if len(vectors) != len(texts):
                raise ValueError("embedding count")
            dimension = len(vectors[0])
            checked = tuple(validate_vector(v, dimension) for v in vectors)
            usage = {k: value[k] for k in ("prompt_eval_count",) if k in value} or None
            return EmbeddingBatch(
                vectors=checked, model_id=value["model"], model_digest=digest, usage=usage
            )
        except (httpx.HTTPError, ValueError, KeyError, StopIteration, TypeError, IndexError):
            raise DomainError(
                "EMBEDDING_UNAVAILABLE", "Embedding provider failed its response contract"
            ) from None
