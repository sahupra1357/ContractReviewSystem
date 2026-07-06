"""Layer 2 — fail-closed tripwire (§3.3). DETECTOR ONLY, never masks.

Runs on the Layer-1-masked text. Any flag of a possible unregistered entity
halts the document in pii_hold for human resolution. Detection is
Presidio (custom threshold, PII-relevant types only) plus local regex
recognizers for entity shapes Presidio misses out of the box (org-suffixed
names, street addresses, account numbers — the G0 smoke test showed
Presidio missing account patterns).

Tuning here trades hold-queue burden vs sensitivity — it can never trade
away safety, because a flag stops the document rather than guessing.
"""

import re
from dataclasses import dataclass

import httpx

from backend.config import get_settings

# Presidio types that indicate a possible unregistered entity in a contract.
# DATE_TIME/URL are excluded: contracts are legitimately full of them.
_PRESIDIO_TYPES = {
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "CREDIT_CARD",
    "US_BANK_NUMBER", "IBAN_CODE", "US_PASSPORT", "US_DRIVER_LICENSE",
}
_PRESIDIO_MIN_SCORE = 0.5

_REGEX_RECOGNIZERS = {
    "org-suffix": re.compile(
        r"\b[A-Z][\w&'-]+(?: [A-Z][\w&'-]+)* (?:LLC|Inc|LP|LLP|Ltd|Co|Corp|GmbH)\b"
    ),
    "street-address": re.compile(
        r"\b\d{1,5} [A-Z][\w'-]+(?: [A-Z][\w'-]+)* "
        r"(?:Road|Rd|Lane|Ln|Drive|Dr|Street|St|Avenue|Ave|Boulevard|Blvd|Way|Court|Ct)\b"
        r"(?:,\s*[A-Z][\w'-]+,\s*[A-Z]{2}\b)?"  # optional ", City, ST" tail
    ),
    "account-number": re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
}

# Masked placeholders like [PERSON-1] must never re-trigger the tripwire.
_PLACEHOLDER = re.compile(r"\[[A-Z]+-\d+\]")


@dataclass
class TripwireFlag:
    flag_type: str
    span_text: str
    start: int
    end: int
    detector: str
    score: float | None


def _inside_placeholder(start: int, end: int, text: str) -> bool:
    return any(m.start() <= start and end <= m.end() for m in _PLACEHOLDER.finditer(text))


def _presidio_flags(text: str, analyzer_url: str) -> list[TripwireFlag]:
    response = httpx.post(
        f"{analyzer_url}/analyze",
        json={"text": text, "language": "en"},
        timeout=60.0,
    )
    response.raise_for_status()
    flags = []
    for finding in response.json():
        if finding["entity_type"] not in _PRESIDIO_TYPES:
            continue
        if finding["score"] < _PRESIDIO_MIN_SCORE:
            continue
        start, end = finding["start"], finding["end"]
        if _inside_placeholder(start, end, text):
            continue
        flags.append(
            TripwireFlag(
                flag_type=finding["entity_type"],
                span_text=text[start:end],
                start=start,
                end=end,
                detector="presidio",
                score=finding["score"],
            )
        )
    return flags


def _regex_flags(text: str) -> list[TripwireFlag]:
    flags = []
    for name, pattern in _REGEX_RECOGNIZERS.items():
        for m in pattern.finditer(text):
            if _inside_placeholder(m.start(), m.end(), text):
                continue
            flags.append(
                TripwireFlag(
                    flag_type=name.upper().replace("-", "_"),
                    span_text=m.group(),
                    start=m.start(),
                    end=m.end(),
                    detector=f"regex:{name}",
                    score=None,
                )
            )
    return flags


def detect(
    text: str,
    *,
    analyzer_url: str | None = None,
    suppressed_spans: set[tuple[str, str]] | None = None,
) -> list[TripwireFlag]:
    """Return flags on possible unregistered PII in Layer-1-masked text.

    suppressed_spans: {(flag_type, span_text)} previously dismissed by a
    human with rationale — suppressing them lets a re-run proceed without
    re-flagging the identical span.
    """
    url = analyzer_url or get_settings().presidio_analyzer_url
    flags = _presidio_flags(text, url) + _regex_flags(text)
    if suppressed_spans:
        flags = [
            f for f in flags
            if (f.flag_type, f.span_text.strip()) not in suppressed_spans
        ]
    # de-duplicate overlapping detections of the same span text
    unique: dict[tuple[str, str], TripwireFlag] = {}
    for f in flags:
        unique.setdefault((f.flag_type, f.span_text.strip()), f)
    return list(unique.values())
