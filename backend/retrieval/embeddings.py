"""Embedding providers.

* ``OllamaEmbedder`` — local models (``nomic-embed-text`` by default), used for local dev and the benchmark.
* ``OpenAIEmbedder`` / ``VoyageEmbedder`` — managed APIs for cloud deployments.
* ``HashingEmbedder`` — deterministic feature hashing for unit tests only (no semantics).

All vectors are L2-normalised so cosine similarity is a dot product.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from typing import Any, Protocol

import httpx

from backend.common.retry import RetryPolicy, retry_async
from backend.config.settings import Settings
from backend.retrieval.bm25 import tokenize

# Some embedding models are trained with task prefixes.
_TASK_PREFIXES: dict[str, tuple[str, str]] = {
    "nomic-embed-text": ("search_document: ", "search_query: "),
    "mxbai-embed-large": ("", "Represent this sentence for searching relevant passages: "),
}


def _require(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"{name} must be set for this provider")
    return value


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


class Embedder(Protocol):
    model: str
    dim: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...

    async def aclose(self) -> None: ...


class HashingEmbedder:
    """Signed feature hashing over unigrams + bigrams. Test double — not a semantic model."""

    def __init__(self, dim: int = 256) -> None:
        self.model = f"hashing-{dim}"
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = tokenize(text)
        features = tokens + [f"{a} {b}" for a, b in itertools.pairwise(tokens)]
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[index] += sign
        return _normalize(vec)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    async def aclose(self) -> None:
        return None


class OllamaEmbedder:
    def __init__(self, model: str, dim: int, base_url: str, batch_size: int = 16) -> None:
        self.model = model
        self.dim = dim
        self._batch = batch_size
        self._doc_prefix, self._query_prefix = _TASK_PREFIXES.get(model.split(":")[0], ("", ""))
        self._client = httpx.AsyncClient(base_url=base_url, timeout=120.0)
        self._retry = RetryPolicy(max_attempts=3, base_delay_s=0.5)

    async def _embed(self, inputs: list[str]) -> list[list[float]]:
        async def call() -> list[list[float]]:
            response = await self._client.post("/api/embed", json={"model": self.model, "input": inputs})
            response.raise_for_status()
            vectors: list[list[float]] = response.json()["embeddings"]
            return vectors

        vectors, _ = await retry_async(call, self._retry, lambda e: isinstance(e, httpx.TransportError))
        if vectors and len(vectors[0]) != self.dim:
            raise ValueError(
                f"{self.model} returned dim {len(vectors[0])}, expected EMBEDDING_DIM={self.dim}"
            )
        return [_normalize(v) for v in vectors]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            out.extend(await self._embed([self._doc_prefix + t for t in texts[i : i + self._batch]]))
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([self._query_prefix + text]))[0]

    async def aclose(self) -> None:
        await self._client.aclose()


class OpenAIEmbedder:
    """OpenAI embeddings; pass an ``AsyncAzureOpenAI`` client to use an Azure OpenAI deployment."""

    def __init__(
        self,
        model: str,
        dim: int,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        import openai

        self.model = model
        self.dim = dim
        self._client = client or openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            response = await self._client.embeddings.create(
                model=self.model, input=texts[i : i + 64], dimensions=self.dim
            )
            out.extend(_normalize(list(item.embedding)) for item in response.data)
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]

    async def aclose(self) -> None:
        await self._client.close()


class VoyageEmbedder:
    def __init__(self, model: str, dim: int, api_key: str) -> None:
        self.model = model
        self.dim = dim
        self._client = httpx.AsyncClient(
            base_url="https://api.voyageai.com/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )

    async def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        response = await self._client.post(
            "/embeddings",
            json={
                "model": self.model,
                "input": texts,
                "input_type": input_type,
                "output_dimension": self.dim,
            },
        )
        response.raise_for_status()
        return [_normalize(item["embedding"]) for item in response.json()["data"]]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            out.extend(await self._embed(texts[i : i + 64], "document"))
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], "query"))[0]

    async def aclose(self) -> None:
        await self._client.aclose()


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "hashing":
        return HashingEmbedder(settings.embedding_dim)
    if settings.embedding_provider == "azure_openai":
        import openai

        from backend.models.azure_auth import token_provider

        use_key = settings.azure_auth == "api_key" and settings.azure_openai_api_key is not None
        client = openai.AsyncAzureOpenAI(
            azure_endpoint=_require(settings.azure_openai_endpoint, "AZURE_OPENAI_ENDPOINT"),
            api_version=settings.azure_openai_api_version,
            api_key=settings.azure_openai_api_key.get_secret_value()
            if use_key and settings.azure_openai_api_key
            else None,
            azure_ad_token_provider=None
            if use_key
            else token_provider(settings.azure_token_scope, settings.azure_client_id),
        )
        # EMBEDDING_MODEL is the Azure deployment name (e.g. a text-embedding-3-small deployment).
        return OpenAIEmbedder(settings.embedding_model, settings.embedding_dim, client=client)
    if settings.embedding_provider == "ollama":
        return OllamaEmbedder(settings.embedding_model, settings.embedding_dim, settings.ollama_base_url)
    if settings.embedding_provider == "openai":
        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        return OpenAIEmbedder(settings.embedding_model, settings.embedding_dim, key, settings.openai_base_url)
    if settings.voyage_api_key is None:
        raise ValueError("EMBEDDING_PROVIDER=voyage requires VOYAGE_API_KEY")
    return VoyageEmbedder(
        settings.embedding_model, settings.embedding_dim, settings.voyage_api_key.get_secret_value()
    )
