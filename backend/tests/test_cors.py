"""CORS allowlist — the SPA may be hosted apart from the API (Vercel)."""

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import allowed_origins, app


@pytest.fixture
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_vite_dev_origin_allowed_by_default(clear_settings_cache):
    assert "http://localhost:5173" in allowed_origins()


def test_configured_origins_are_added(monkeypatch, clear_settings_cache):
    monkeypatch.setenv(
        "CRS_CORS_ALLOW_ORIGINS", "https://crs.vercel.app, https://preview.vercel.app/"
    )
    origins = allowed_origins()
    # trailing slash stripped: browsers send the Origin header without one
    assert "https://crs.vercel.app" in origins
    assert "https://preview.vercel.app" in origins
    assert "http://localhost:5173" in origins


def test_blank_config_adds_nothing(monkeypatch, clear_settings_cache):
    monkeypatch.setenv("CRS_CORS_ALLOW_ORIGINS", "  ,  ")
    assert allowed_origins() == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_no_wildcard_origin(clear_settings_cache):
    # a Bearer-token API must never answer with allow-origin *
    assert "*" not in allowed_origins()


def test_preflight_from_dev_origin_is_allowed():
    client = TestClient(app)
    response = client.options(
        "/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
