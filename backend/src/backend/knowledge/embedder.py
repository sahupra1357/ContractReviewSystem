"""Embedders (design §3.4). MASKED text only ever reaches these.

BgeM3Embedder — self-hosted BAAI/bge-m3 via sentence-transformers (the
design's named choice; no external API call). Loaded lazily: the model is
~2.3 GB and only index/query paths need it. HashEmbedder is the deterministic
test double (also used in CI where torch isn't installed).

OpenAIEmbedder — hosted alternative for deployment targets that cannot fit
torch in memory (the free-tier demo). It is NOT the design default: it sends
masked text to a third party, so it stays opt-in via CRS_EMBEDDING_PROVIDER
and the in-VPC build keeps BGE-M3.
"""

import hashlib
import math
from typing import Protocol

from backend.config import get_settings
from backend.knowledge.models import EMBEDDING_DIM


class Embedder(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class BgeM3Embedder:
    model_name = "BAAI/bge-m3"

    def __init__(self) -> None:
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]


class OpenAIEmbedder:
    """OpenAI (or any OpenAI-compatible) embeddings, truncated to EMBEDDING_DIM.

    text-embedding-3-* accept a `dimensions` argument, so asking for 1024 keeps
    the existing pgvector column and needs no migration. Older models that
    ignore it are rejected loudly rather than silently writing wrong-width
    vectors.
    """

    DEFAULT_MODEL = "text-embedding-3-small"

    def __init__(self) -> None:
        settings = get_settings()
        self._model_id = settings.embedding_model or self.DEFAULT_MODEL
        self._api_key = settings.embedding_api_key
        self._base_url = settings.embedding_base_url
        self._client = None
        # provider-qualified: partitions the embedding cache and the dense-search
        # filter, so BGE-M3 and OpenAI vectors never mix in one index
        self.model_name = f"openai:{self._model_id}"

    def _load(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._load().embeddings.create(
            model=self._model_id, input=texts, dimensions=EMBEDDING_DIM
        )
        vectors = [item.embedding for item in sorted(response.data, key=lambda d: d.index)]
        for vec in vectors:
            if len(vec) != EMBEDDING_DIM:
                raise ValueError(
                    f"{self._model_id} returned {len(vec)}-dim vectors, expected "
                    f"{EMBEDDING_DIM}; pick a model supporting the `dimensions` argument"
                )
        return vectors


class HashEmbedder:
    """Deterministic pseudo-embeddings: identical text → identical vector,
    token overlap → similar vectors. Good enough to test caching, storage,
    and ranking plumbing without torch."""

    model_name = "hash-test"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * EMBEDDING_DIM
            for token in text.lower().split():
                idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % EMBEDDING_DIM
                vec[idx] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


_PROVIDERS = {
    "bge-m3": BgeM3Embedder,
    "openai": OpenAIEmbedder,
    "hash": HashEmbedder,   # tests and smoke runs only — not a quality option
}


def get_embedder() -> Embedder:
    provider = get_settings().embedding_provider
    try:
        return _PROVIDERS[provider]()
    except KeyError:
        raise ValueError(
            f"unknown CRS_EMBEDDING_PROVIDER {provider!r}; expected one of "
            f"{', '.join(sorted(_PROVIDERS))}"
        ) from None
