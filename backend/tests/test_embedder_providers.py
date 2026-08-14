"""Embedder provider selection (design §3.4).

BGE-M3 stays the default everywhere; OpenAI is opt-in for hosts too small for
torch. The critical property is that provider vectors can never mix in one
index — model_name partitions both the embedding cache and dense retrieval.
"""

import pytest

from backend.config import get_settings
from backend.knowledge.embedder import (
    BedrockEmbedder,
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


class _FakeBody:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        import json

        return json.dumps(self._payload).encode()


class _FakeBedrockClient:
    def __init__(self, dim):
        self.dim = dim
        self.calls = []

    def invoke_model(self, *, modelId, body):
        import json

        self.calls.append({"modelId": modelId, "body": json.loads(body)})
        return {"body": _FakeBody({"embedding": [0.1] * self.dim})}


def test_bedrock_provider_selected_by_config(monkeypatch):
    monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", "bedrock")
    embedder = get_embedder()
    assert isinstance(embedder, BedrockEmbedder)
    assert embedder.model_name == "bedrock:amazon.titan-embed-text-v2:0"


def test_bedrock_requests_column_width_and_normalizes(monkeypatch):
    monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", "bedrock")
    embedder = get_embedder()
    fake = _FakeBedrockClient(EMBEDDING_DIM)
    monkeypatch.setattr(embedder, "_load", lambda: fake)

    vectors = embedder.embed(["alpha", "beta"])

    assert len(vectors) == 2
    # Titan has no batch call: one invocation per text, order preserved
    assert [c["body"]["inputText"] for c in fake.calls] == ["alpha", "beta"]
    assert fake.calls[0]["body"]["dimensions"] == EMBEDDING_DIM
    # normalized, so pgvector cosine distance matches the BGE-M3 index's meaning
    assert fake.calls[0]["body"]["normalize"] is True


def test_bedrock_rejects_wrong_width_vectors(monkeypatch):
    monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", "bedrock")
    embedder = get_embedder()
    monkeypatch.setattr(embedder, "_load", lambda: _FakeBedrockClient(512))

    with pytest.raises(ValueError, match="expected"):
        embedder.embed(["alpha"])


def test_bedrock_uses_configured_region(monkeypatch):
    monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", "bedrock")
    monkeypatch.setenv("CRS_AWS_REGION", "eu-west-1")
    assert get_embedder()._region == "eu-west-1"


def test_every_provider_has_a_distinct_model_name(monkeypatch):
    names = set()
    for provider in ("bge-m3", "openai", "bedrock", "hash"):
        get_settings.cache_clear()
        monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", provider)
        names.add(get_embedder().model_name)
    # the partition key that stops two providers' vectors being compared
    assert len(names) == 4


def test_openai_empty_input_short_circuits(monkeypatch):
    monkeypatch.setenv("CRS_EMBEDDING_PROVIDER", "openai")
    embedder = get_embedder()
    fake = _FakeClient(EMBEDDING_DIM)
    monkeypatch.setattr(embedder, "_load", lambda: fake)

    assert embedder.embed([]) == []
    assert fake.embeddings.calls == []   # no billable API call
