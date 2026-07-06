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
# minimum heading-overlap score to claim a family match
FAMILY_MIN_SCORE = 0.5


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().upper()


def _norm_heading(heading: str) -> str:
    # "8. LIABILITY" → "8 LIABILITY" (tolerates OCR punctuation drift)
    return re.sub(r"[^\w ]", "", _norm(heading)).strip()


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
    deviations: list[SectionDiff]
    missing: list[MissingClause]
    extra: list[SectionDiff]   # sections with no template counterpart


def detect_family(sections: list[dict]) -> tuple[str | None, float]:
    doc_headings = {_norm_heading(s["heading"]) for s in sections}
    best, best_score = None, 0.0
    for family, template in FAMILIES.items():
        template_headings = [_norm_heading(h) for h, _ in template["sections"]]
        score = sum(1 for h in template_headings if h in doc_headings) / len(template_headings)
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
                        deviations=[], missing=[], extra=[])

    seen_template_headings: set[str] = set()
    for section in sections:
        key = _norm_heading(section["heading"])
        doc_text = masked_text[section["start"]:section["end"]].strip()
        entry = template_by_heading.get(key)
        if entry is None:
            if key and "PREAMBLE" not in key:
                result.extra.append(SectionDiff(
                    section_id=section["section_id"], heading=section["heading"],
                    doc_text=doc_text, template_text="", similarity=0.0))
            continue
        seen_template_headings.add(key)
        heading, body = entry
        similarity = SequenceMatcher(
            None, _template_norm(body), _doc_norm(doc_text)
        ).ratio()
        diff = SectionDiff(
            section_id=section["section_id"], heading=section["heading"],
            doc_text=doc_text, template_text=body, similarity=similarity,
        )
        (result.standard if similarity >= DEVIATION_THRESHOLD
         else result.deviations).append(diff)

    for key, (heading, body) in template_by_heading.items():
        if key not in seen_template_headings and "SIGNATURES" not in key:
            result.missing.append(MissingClause(
                template_ref=f"template:{family}:{heading}",
                heading=heading, template_text=body,
            ))
    return result
