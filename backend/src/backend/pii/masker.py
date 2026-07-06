"""Layer 1 — deterministic masking from the PII master table (§3.3).

The ONLY component that masks. Matching is fuzzy where OCR mutates
separators — "Jordan Rivera" also matches "Jordan  Rivera" or
"Jordan- Rivera", and "4471-3920-0011" matches "4471 - 3920 - 0011" —
but token content must match exactly (recall 1.0 on registered entities is
by construction; separators are the only degree of freedom).
"""

import re
from dataclasses import dataclass


@dataclass
class MaskedEntity:
    placeholder: str      # "[PERSON-1]"
    value: str            # canonical registered value
    entity_type: str
    occurrences: int


def _entity_pattern(value: str) -> re.Pattern:
    """Tokens joined by a small class of separators (whitespace/punctuation,
    max 3 chars) — tolerant to OCR spacing, strict on content."""
    tokens = re.findall(r"\w+", value)
    body = r"[\W_]{0,3}".join(re.escape(t) for t in tokens)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def mask_text(
    text: str, known_entities: list[tuple[str, str]]
) -> tuple[str, list[MaskedEntity]]:
    """Replace every occurrence of each (value, entity_type) with a stable
    per-document placeholder. Longer entities first so 'Acme Property
    Holdings LLC' wins over any shorter overlapping entry."""
    masked = text
    results: list[MaskedEntity] = []
    counters: dict[str, int] = {}

    for value, entity_type in sorted(known_entities, key=lambda e: -len(e[0])):
        pattern = _entity_pattern(value)
        if not pattern.search(masked):
            continue
        counters[entity_type] = counters.get(entity_type, 0) + 1
        placeholder = f"[{entity_type}-{counters[entity_type]}]"
        masked, count = pattern.subn(placeholder, masked)
        results.append(
            MaskedEntity(
                placeholder=placeholder,
                value=value,
                entity_type=entity_type,
                occurrences=count,
            )
        )
    return masked, results
