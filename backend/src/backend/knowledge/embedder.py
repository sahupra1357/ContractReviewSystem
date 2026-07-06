"""Embedders (design §3.4). MASKED text only ever reaches these.

BgeM3Embedder — self-hosted BAAI/bge-m3 via sentence-transformers (the
design's named choice; no external API call). Loaded lazily: the model is
~2.3 GB and only index/query paths need it. HashEmbedder is the deterministic
test double (also used in CI where torch isn't installed).
"""

import hashlib
import math
from typing import Protocol

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


def get_embedder() -> Embedder:
    return BgeM3Embedder()
