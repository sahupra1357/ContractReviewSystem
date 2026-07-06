"""Template family detection + clause-level deviation diff (design §3.5).

Deterministic and cheap: family is detected by heading overlap; each section
is compared against the family's standard text. Only DEVIATIONS go to the
LLM — the efficiency lever from the brainstorm (docs/01 §3.3). Runs entirely
on MASKED text.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from backend.analysis.reference_templates import FAMILIES

# below this similarity a present section counts as deviating from standard
DEVIATION_THRESHOLD = 0.70
# between the two thresholds the section is BORDERLINE — sent to the LLM for
# judgment (short identifier-heavy clauses and subtle rewrites overlap in
# similarity space; measured on the golden corpus in Phase 7)
STANDARD_THRESHOLD = 0.85
# minimum heading-overlap score to claim a family match
FAMILY_MIN_SCORE = 0.5


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().upper()


def _norm_heading(heading: str) -> str:
    # "8. LIABILITY" → "8 LIABILITY" (tolerates OCR punctuation drift)
    return re.sub(r"[^\w ]", "", _norm(heading)).strip()


_HEADING_FUZZ = 0.8


def _headings_match(a: str, b: str) -> bool:
    """OCR-tolerant heading comparison: normalized exact, or fuzzy ≥ 0.8
    (poor scans garble letters — 'INSURANCE' → 'INSURANGE')."""
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= _HEADING_FUZZ


def _find_heading(key: str, candidates: dict[str, tuple[str, str]]):
    """Return (template_key, entry) for an exact or fuzzy heading match."""
    if key in candidates:
        return key, candidates[key]
    for cand_key, entry in candidates.items():
        if _headings_match(key, cand_key):
            return cand_key, entry
    return None, None


def _template_norm(body: str) -> str:
    # strip {slot} markers — slot values differ per contract by design
    return _norm(re.sub(r"\{\w+\}", " ", body))


def _doc_norm(section_text: str) -> str:
    # drop the heading line and PII placeholders/values noise so short
    # sections compare on their legal wording, not on identifiers
    body = re.sub(r"^[^\n]*\n", "", section_text, count=1)
    body = re.sub(r"\[[A-Z]+-\d+\]", " ", body)          # [PERSON-1] etc.
    body = re.sub(r"\b(USD [\d,]+|20\d{2}-\d{2}-\d{2})\b", " ", body)
    return _norm(body)


@dataclass
class SectionDiff:
    section_id: str
    heading: str
    doc_text: str
    template_text: str
    similarity: float


@dataclass
class MissingClause:
    template_ref: str        # "template:<family>:<heading>"
    heading: str
    template_text: str


@dataclass
class DiffResult:
    family: str | None
    family_score: float
    standard: list[SectionDiff]
    borderline: list[SectionDiff]  # LLM verifies these (0.70 ≤ sim < 0.85)
    deviations: list[SectionDiff]
    missing: list[MissingClause]
    extra: list[SectionDiff]   # sections with no template counterpart


def detect_family(sections: list[dict]) -> tuple[str | None, float]:
    doc_headings = {_norm_heading(s["heading"]) for s in sections}
    best, best_score = None, 0.0
    for family, template in FAMILIES.items():
        template_headings = [_norm_heading(h) for h, _ in template["sections"]]
        score = sum(
            1 for h in template_headings
            if any(_headings_match(h, d) for d in doc_headings)
        ) / len(template_headings)
        if score > best_score:
            best, best_score = family, score
    if best_score < FAMILY_MIN_SCORE:
        return None, best_score
    return best, best_score


def diff_against_family(
    family: str, sections: list[dict], masked_text: str
) -> DiffResult:
    template = FAMILIES[family]
    template_by_heading = {
        _norm_heading(heading): (heading, body) for heading, body in template["sections"]
    }
    result = DiffResult(family=family, family_score=1.0, standard=[],
                        borderline=[], deviations=[], missing=[], extra=[])

    seen_template_headings: set[str] = set()
    for section in sections:
        key = _norm_heading(section["heading"])
        doc_text = masked_text[section["start"]:section["end"]].strip()
        template_key, entry = _find_heading(key, template_by_heading)
        if entry is None:
            if key and "PREAMBLE" not in key:
                result.extra.append(SectionDiff(
                    section_id=section["section_id"], heading=section["heading"],
                    doc_text=doc_text, template_text="", similarity=0.0))
            continue
        seen_template_headings.add(template_key)
        heading, body = entry
        similarity = SequenceMatcher(
            None, _template_norm(body), _doc_norm(doc_text)
        ).ratio()
        diff = SectionDiff(
            section_id=section["section_id"], heading=section["heading"],
            doc_text=doc_text, template_text=body, similarity=similarity,
        )
        if similarity >= STANDARD_THRESHOLD:
            result.standard.append(diff)
        elif similarity >= DEVIATION_THRESHOLD:
            result.borderline.append(diff)
        else:
            result.deviations.append(diff)

    for key, (heading, body) in template_by_heading.items():
        if key not in seen_template_headings and "SIGNATURES" not in key:
            result.missing.append(MissingClause(
                template_ref=f"template:{family}:{heading}",
                heading=heading, template_text=body,
            ))
    return result
