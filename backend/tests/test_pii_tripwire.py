import backend.pii.tripwire as tripwire
from backend.pii.tripwire import TripwireFlag, _regex_flags, detect


def test_regex_catches_org_suffix_and_address_and_account():
    text = ("Bluefin Restoration Co will service 47 Old Mill Road for "
            "payment to 7719-4402-8873.")
    flags = {f.flag_type for f in _regex_flags(text)}
    assert flags == {"ORG_SUFFIX", "STREET_ADDRESS", "ACCOUNT_NUMBER"}


def test_regex_ignores_masked_placeholders():
    assert _regex_flags("Vendor [ORG-1] paid [ACCOUNT-1] on time.") == []


def _fake_presidio(monkeypatch, findings):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return findings

    monkeypatch.setattr(tripwire.httpx, "post", lambda *a, **k: FakeResponse())


def test_detect_filters_types_and_scores(monkeypatch):
    text = "Tobias Lindqvist met on 2026-03-01 maybe."
    _fake_presidio(monkeypatch, [
        {"entity_type": "PERSON", "score": 0.85,
         "start": 0, "end": 16},
        {"entity_type": "DATE_TIME", "score": 0.95,          # excluded type
         "start": 24, "end": 34},
        {"entity_type": "PERSON", "score": 0.2,              # below threshold
         "start": 35, "end": 40},
    ])
    flags = detect(text, analyzer_url="http://fake")
    assert [(f.flag_type, f.span_text) for f in flags] == [("PERSON", "Tobias Lindqvist")]


def test_detect_suppresses_dismissed_spans(monkeypatch):
    text = "Tobias Lindqvist attended."
    _fake_presidio(monkeypatch, [
        {"entity_type": "PERSON", "score": 0.85, "start": 0, "end": 16},
    ])
    flags = detect(
        text, analyzer_url="http://fake",
        suppressed_spans={("PERSON", "Tobias Lindqvist")},
    )
    assert flags == []


def test_detect_deduplicates_same_span(monkeypatch):
    text = "Account 7719-4402-8873 and again 7719-4402-8873."
    _fake_presidio(monkeypatch, [])
    flags = detect(text, analyzer_url="http://fake")
    account_flags = [f for f in flags if f.flag_type == "ACCOUNT_NUMBER"]
    assert len(account_flags) == 1
    assert isinstance(account_flags[0], TripwireFlag)
