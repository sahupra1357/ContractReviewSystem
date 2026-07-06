"""Gate G5 eval — analysis quality on the golden corpus, with a REAL LLM.

Usage (from backend/, compose stack up, corpus indexed via index_golden,
LLM credentials configured — CRS_LLM_* / ANTHROPIC_API_KEY / local proxy):
    CRS_DATABASE_URL=postgresql+psycopg://crs:crs@localhost:5433/crs \
        uv run python -m backend.eval.analysis_eval

Measures, per docs/02_sdlc_plan.md Gate G5:
  1. HARD: known-issue detection rate ≥ 0.80 — every labels.yaml known_issue
     must be matched by a finding citing the labeled clause (chunk of that
     section, or the template_ref for removed clauses).
  2. HARD: zero uncited findings displayed (guaranteed by construction —
     the groundedness gate drops them; the DROP COUNT is reported).
  3. INFO: clean-doc false positives (high-severity findings on
     expected_clean docs).
  4. HARD: per-document analysis latency within the minutes SLA (< 5 min).
"""

import re
import sys

import yaml
from sqlalchemy import select

from backend.analysis.models import Analysis
from backend.db import get_sessionmaker
from backend.eval.extraction_eval import GOLDEN
from backend.knowledge.models import Chunk
from backend.models import Document
from backend.storage import S3MaskedStorage, S3RawStorage
from backend.worker import process_one

DETECTION_THRESHOLD = 0.80
LATENCY_SLA_MS = 5 * 60 * 1000


def _clause_ref_to_section(clause_ref: str) -> str:
    match = re.match(r"(\d+)", clause_ref)
    return f"sec-{match.group(1)}" if match else clause_ref


def evaluate() -> int:
    sessionmaker = get_sessionmaker()
    raw, masked = S3RawStorage(), S3MaskedStorage()

    # drain pending analyze jobs (index_golden left them queued)
    drained = 0
    while True:
        with sessionmaker() as session:
            if not process_one(session, raw, masked, stage="analyze"):
                break
            drained += 1
    print(f"analyze jobs drained: {drained}")

    detected = total_issues = 0
    clean_docs = clean_false_positives = 0
    dropped_total = 0
    latencies: list[int] = []
    with sessionmaker() as session:
        for labels_path in sorted(GOLDEN.glob("docs/*/labels.yaml")):
            labels = yaml.safe_load(labels_path.read_text())
            doc = session.execute(select(Document).where(
                Document.filename.like(f"{labels['doc_id']}.%"))).scalar_one_or_none()
            if doc is None:
                print(f"  {labels['doc_id']}  NOT IN CORPUS — run index_golden first")
                return 1
            analysis = session.execute(select(Analysis).where(
                Analysis.document_id == doc.id)).scalar_one_or_none()
            if analysis is None:
                print(f"  {labels['doc_id']}  status={doc.status} — no analysis row")
                return 1

            chunk_section_by_id = {
                c.id: c.section_id for c in session.execute(
                    select(Chunk).where(Chunk.document_id == doc.id)).scalars()
            }
            cited_sections = set()
            for f in analysis.findings:
                citation = f.get("citation", "")
                if citation.startswith("template:"):
                    heading = citation.split(":", 2)[2]
                    cited_sections.add(_clause_ref_to_section(heading))
                else:
                    cited_sections.add(chunk_section_by_id.get(citation))

            hits = []
            for issue in labels["known_issues"]:
                total_issues += 1
                section = _clause_ref_to_section(issue["clause_ref"])
                hit = section in cited_sections
                detected += hit
                hits.append((issue["id"], hit))

            if labels["expected_clean"]:
                clean_docs += 1
                high = [f for f in analysis.findings if f.get("severity") == "high"]
                clean_false_positives += bool(high)

            dropped_total += analysis.dropped_uncited
            latencies.append(analysis.latency_ms)
            misses = [i for i, h in hits if not h]
            print(f"  {labels['doc_id']}  family={analysis.family or 'MANUAL-REVIEW':20s} "
                  f"findings={len(analysis.findings)} dropped={analysis.dropped_uncited} "
                  f"latency={analysis.latency_ms / 1000:.1f}s "
                  f"{'MISSED: ' + ','.join(misses) if misses else 'ok'}")

    rate = detected / total_issues if total_issues else 1.0
    max_latency = max(latencies)
    ok_rate = rate >= DETECTION_THRESHOLD
    ok_latency = max_latency < LATENCY_SLA_MS
    print(f"\n== Gate G5 results ({len(latencies)} docs) ==")
    print(f"  {'PASS' if ok_rate else 'FAIL'}  known-issue detection: "
          f"{rate:.3f} ({detected}/{total_issues}, >= {DETECTION_THRESHOLD})")
    print(f"  PASS  uncited findings displayed: 0 by construction "
          f"(groundedness gate dropped {dropped_total})")
    print(f"  {'PASS' if ok_latency else 'FAIL'}  max latency: "
          f"{max_latency / 1000:.1f}s (SLA {LATENCY_SLA_MS / 1000:.0f}s)")
    print(f"  info  clean-doc high-severity false positives: "
          f"{clean_false_positives}/{clean_docs}")
    return 0 if (ok_rate and ok_latency) else 1


if __name__ == "__main__":
    sys.exit(evaluate())
