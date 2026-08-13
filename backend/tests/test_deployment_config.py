"""Startup guard: a real deployment must not silently run on dev defaults.

The failure this prevents is quiet, not loud — a hosted service with no
CRS_DATABASE_URL dials localhost and looks like a network problem, and one with
no CRS_JWT_SECRET signs tokens with the published dev secret while appearing to
work perfectly.
"""

import os

import pytest

from backend.config import (
    Settings,
    deployment_config_problems,
    require_valid_deployment_config,
)


@pytest.fixture(autouse=True)
def no_ambient_config(monkeypatch):
    """Hide any CRS_* the surrounding environment happens to export.

    These tests assert "is this setting still the dev default?", so ambient
    configuration changes the answer. CI exports CRS_DATABASE_URL for the
    invariant suite, which made the unconfigured-deployment cases pass locally
    and fail in CI.
    """
    for key in list(os.environ):
        if key.startswith("CRS_"):
            monkeypatch.delenv(key, raising=False)


def _settings(**overrides) -> Settings:
    """Settings isolated from both the environment and any local .env file."""
    return Settings(_env_file=None, **overrides)


DEPLOYED = {
    "environment": "render-free",
    "database_url": "postgresql://u:p@db.example/crs",
    "s3_endpoint_url": "https://acct.r2.cloudflarestorage.com",
    "s3_access_key": "real-key",
    "s3_secret_key": "real-secret",
    "presidio_analyzer_url": "https://x--presidio.modal.run",
    "jwt_secret": "a-long-random-production-value",
}


@pytest.mark.parametrize("environment", ["local", "compose"])
def test_dev_environments_are_exempt(environment):
    # compose deliberately relies on the MinIO and JWT dev defaults
    assert deployment_config_problems(_settings(environment=environment)) == []


def test_fully_configured_deployment_passes():
    assert deployment_config_problems(_settings(**DEPLOYED)) == []


def test_unconfigured_deployment_reports_every_problem():
    problems = deployment_config_problems(_settings(environment="render-free"))
    reported = " ".join(problems)
    for key in (
        "CRS_DATABASE_URL",
        "CRS_S3_ENDPOINT_URL",
        "CRS_S3_ACCESS_KEY",
        "CRS_S3_SECRET_KEY",
        "CRS_PRESIDIO_ANALYZER_URL",
        "CRS_JWT_SECRET",
    ):
        assert key in reported, f"{key} not flagged"


def test_dev_jwt_secret_alone_is_flagged():
    # the dangerous case: everything else set, so the app looks healthy
    settings = _settings(**{**DEPLOYED, "jwt_secret": "dev-secret-change-me"})
    problems = deployment_config_problems(settings)
    assert len(problems) == 1
    assert "CRS_JWT_SECRET" in problems[0]


def test_openai_embeddings_require_a_key():
    problems = deployment_config_problems(
        _settings(**DEPLOYED, embedding_provider="openai")
    )
    assert any("CRS_EMBEDDING_API_KEY" in p for p in problems)

    ok = deployment_config_problems(
        _settings(**DEPLOYED, embedding_provider="openai", embedding_api_key="sk-x")
    )
    assert ok == []


def test_bge_m3_needs_no_embedding_key():
    assert deployment_config_problems(_settings(**DEPLOYED, embedding_provider="bge-m3")) == []


def test_require_raises_with_actionable_message():
    with pytest.raises(RuntimeError) as exc:
        require_valid_deployment_config(_settings(environment="render-free"))
    message = str(exc.value)
    assert "Refusing to start" in message
    assert "render-free" in message
    assert "CRS_DATABASE_URL" in message


def test_require_is_silent_when_configured():
    require_valid_deployment_config(_settings(**DEPLOYED))
