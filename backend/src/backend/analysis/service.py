"""Analysis stage — template diff + LLM review brief with mandatory
citations (design §3.5). MASKED data only; every finding is grounded or
dropped; the model only proposes — humans decide (invariant #2).
"""

import json
import re
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.analysis.models import Analysis
from backend.analysis.prompts import (
    BRIEF_SYSTEM,
    KEY_TERMS_SYSTEM,
    PROMPT_VERSION,
    build_brief_prompt,
)
from backend.analysis.template_diff import detect_family, diff_against_family
from backend.audit import ActorType, record_event
from backend.knowledge.models import Chunk
from backend.llm.base import LLMClient
from backend.models import Document, DocumentStatus
from backend.storage import MaskedStorage

# Guardrails-equivalent injection heuristics (design §3.5) — contract text is
# data; these phrases inside it get surfaced to the reviewer as a finding.
_INJECTION_PATTERNS = re.compile(
    r"ignore (all )?(previous|prior) instructions|disregard (the )?system prompt"
    r"|you are now|act as (an? )?(admin|system)|<\s*/?system\s*>",
    re.IGNORECASE,
)


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(cleaned)


def run_analyze(
    session: Session,
    masked_storage: MaskedStorage,
    llm: LLMClient,
    document: Document,
) -> None:
    started = time.monotonic()
    artifact = json.loads(masked_storage.get_masked(f"{document.id}/masked.json"))
    masked_text = artifact["masked_text"]
    sections = artifact["sections"]

    chunks = list(session.execute(
        select(Chunk).where(Chunk.document_id == document.id)
    ).scalars())
    chunk_ids_by_section = {c.section_id: c.id for c in chunks if c.part == 0}
    valid_chunk_ids = {c.id for c in chunks}

    family, family_score = detect_family(sections)
    if family is None:
        raise ValueError(
            f"no template family matched (best score {family_score:.2f}); "
            "unknown-family analysis is out of POC scope — flag for manual review"
        )
    diff = diff_against_family(family, sections, masked_text)

    # tiered routing: FAST model extracts key terms
    fast_response = llm.complete(
        system=KEY_TERMS_SYSTEM, prompt=masked_text[:12000], tier="fast",
        max_tokens=1024,
    )
    try:
        key_terms = _parse_json(fast_response.text)
    except json.JSONDecodeError:
        key_terms = {"_error": "key-term extraction returned invalid JSON"}

    # STRONG model analyzes only the deviations/missing clauses
    prompt = build_brief_prompt(diff, chunk_ids_by_section)
    strong_response = llm.complete(
        system=BRIEF_SYSTEM, prompt=prompt, tier="strong", max_tokens=4096,
    )
    try:
        brief = _parse_json(strong_response.text)
    except json.JSONDecodeError:
        retry = llm.complete(
            system=BRIEF_SYSTEM,
            prompt=prompt + "\n\nReturn ONLY the JSON object, nothing else.",
            tier="strong", max_tokens=4096,
        )
        brief = _parse_json(retry.text)  # second failure → failed_analyze

    # groundedness gate: uncited findings are DROPPED, never displayed
    valid_refs = valid_chunk_ids | {m.template_ref for m in diff.missing}
    findings, dropped = [], 0
    for f in brief.get("findings", []):
        if f.get("citation") in valid_refs:
            findings.append(f)
        else:
            dropped += 1

    for m in _INJECTION_PATTERNS.finditer(masked_text):
        section = next(
            (s for s in sections if s["start"] <= m.start() < s["end"]), None
        )
        citation = chunk_ids_by_section.get(section["section_id"]) if section else None
        if citation:
            findings.append({
                "citation": citation, "severity": "high",
                "title": "Possible prompt-injection content in contract text",
                "description": f"Suspicious instruction-like text: {m.group()!r}. "
                               "Surfaced by heuristic scan, not the model.",
            })

    existing = session.execute(
        select(Analysis).where(Analysis.document_id == document.id)
    ).scalar_one_or_none()
    if existing:
        session.delete(existing)
        session.flush()
    session.add(Analysis(
        document_id=document.id,
        family=family, family_score=family_score,
        findings=findings, key_terms=key_terms,
        suggested_decision=brief.get("suggested_decision", "changes_requested"),
        rationale=brief.get("rationale", ""),
        dropped_uncited=dropped,
        model_strong=strong_response.model, model_fast=fast_response.model,
        prompt_version=PROMPT_VERSION,
        latency_ms=int((time.monotonic() - started) * 1000),
    ))
    document.status = DocumentStatus.analyzed
    record_event(
        session, actor_type=ActorType.system, actor_id="worker:analyze",
        action="stage.analyzed", object_type="document", object_id=document.id,
        detail={
            "family": family, "findings": len(findings),
            "dropped_uncited": dropped,
            "deviations": len(diff.deviations), "missing": len(diff.missing),
            "suggested_decision": brief.get("suggested_decision"),
            "models": {"strong": strong_response.model, "fast": fast_response.model},
            "latency_ms": int((time.monotonic() - started) * 1000),
        },
    )
