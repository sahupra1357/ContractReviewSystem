"""Embedder provider selection (design §3.4).

BGE-M3 stays the default everywhere; OpenAI is opt-in for hosts too small for
torch. The critical property is that provider vectors can never mix in one
index — model_name partitions both the embedding cache and dense retrieval.
"""

import pytest

from backend.config import get_settings
from backend.knowledge.embedder import (
    BgeM3Embedder,
    HashEmbedder,
    OpenAIEmbedder,
    get_embedder,
)
from backend.knowledge.models import EMBEDDING_DIM


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_default_provider_is_still_bge_m3():
    # the design's self-hosted choice must remain the default on every host
    assert isinstance(get_embedder(), BgeM3Embedder)


def test_openai_provider_selected_by_config(monkeypatch):
    monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", "openai")
    assert isinstance(get_embedder(), OpenAIEmbedder)


def test_hash_provider_selected_by_config(monkeypatch):
    monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", "hash")
    assert isinstance(get_embedder(), HashEmbedder)


def test_unknown_provider_fails_loudly(monkeypatch):
    monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", "nope")
    with pytest.raises(ValueError, match="unknown CRS_EMBEDDING_PROVIDER"):
        get_embedder()


def test_model_names_are_distinct_across_providers(monkeypatch):
    monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", "openai")
    openai_name = get_embedder().model_name
    assert openai_name != BgeM3Embedder.model_name
    assert openai_name != HashEmbedder.model_name
    # provider-qualified so the partition is obvious in the DB
    assert openai_name.startswith("openai:")


def test_openai_default_model_and_override(monkeypatch):
    monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", "openai")
    assert get_embedder().model_name == "openai:text-embedding-3-small"

    get_settings.cache_clear()
    monkeypatch.setenv("CRS_EMBEDDING_MODEL", "text-embedding-3-large")
    assert get_embedder().model_name == "openai:text-embedding-3-large"


class _FakeEmbeddingItem:
    def __init__(self, index, embedding):
        self.index = index
        self.embedding = embedding


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeEmbeddings:
    def __init__(self, dim):
        self.dim = dim
        self.calls = []

    def create(self, *, model, input, dimensions):
        self.calls.append({"model": model, "input": input, "dimensions": dimensions})
        # returned out of order on purpose: the adapter must sort by index
        items = [_FakeEmbeddingItem(i, [0.1] * self.dim) for i in range(len(input))]
        return _FakeResponse(list(reversed(items)))


class _FakeClient:
    def __init__(self, dim):
        self.embeddings = _FakeEmbeddings(dim)


def test_openai_requests_the_column_width(monkeypatch):
    monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", "openai")
    embedder = get_embedder()
    fake = _FakeClient(EMBEDDING_DIM)
    monkeypatch.setattr(embedder, "_load", lambda: fake)

    vectors = embedder.embed(["alpha", "beta"])

    # asking for EMBEDDING_DIM is what keeps the pgvector column migration-free
    assert fake.embeddings.calls[0]["dimensions"] == EMBEDDING_DIM
    assert len(vectors) == 2
    assert all(len(v) == EMBEDDING_DIM for v in vectors)


def test_openai_rejects_wrong_width_vectors(monkeypatch):
    monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", "openai")
    embedder = get_embedder()
    monkeypatch.setattr(embedder, "_load", lambda: _FakeClient(1536))

    # silently storing 1536-dim vectors in a 1024 column must not be possible
    with pytest.raises(ValueError, match="expected"):
        embedder.embed(["alpha"])


def test_openai_empty_input_short_circuits(monkeypatch):
    monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", "openai")
    embedder = get_embedder()
    fake = _FakeClient(EMBEDDING_DIM)
    monkeypatch.setattr(embedder, "_load", lambda: fake)

    assert embedder.embed([]) == []
    assert fake.embeddings.calls == []   # no billable API call
