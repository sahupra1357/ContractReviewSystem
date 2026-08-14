"""Proxy-auth headers for a hosted Presidio analyzer.

Compose and the in-VPC build reach the analyzer inside the network perimeter
and send nothing. A hosted analyzer (Modal) is public by URL alone, so the
tripwire must present credentials — without breaking the unauthenticated case.
"""

import os

import pytest

from backend.config import get_settings
from backend.pii.tripwire import _auth_headers


@pytest.fixture(autouse=True)
def no_ambient_config(monkeypatch):
    for key in list(os.environ):
        if key.startswith("CRS_PRESIDIO_"):
            monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_no_headers_when_unconfigured():
    # compose talks to an in-network analyzer; sending nothing is correct
    assert _auth_headers() == {}


def test_headers_sent_when_both_halves_configured(monkeypatch):
    monkeypatch.setenv("CRS_PRESIDIO_AUTH_KEY", "wk-abc")
    monkeypatch.setenv("CRS_PRESIDIO_AUTH_SECRET", "ws-xyz")
    get_settings.cache_clear()

    assert _auth_headers() == {"Modal-Key": "wk-abc", "Modal-Secret": "ws-xyz"}


@pytest.mark.parametrize(
    "key,secret",
    [("wk-abc", None), (None, "ws-xyz"), ("wk-abc", ""), ("", "ws-xyz")],
)
def test_half_configured_sends_nothing(monkeypatch, key, secret):
    # a half-credential would be rejected anyway; failing to send is clearer
    # than sending something guaranteed to 401
    if key is not None:
        monkeypatch.setenv("CRS_PRESIDIO_AUTH_KEY", key)
    if secret is not None:
        monkeypatch.setenv("CRS_PRESIDIO_AUTH_SECRET", secret)
    get_settings.cache_clear()

    assert _auth_headers() == {}
