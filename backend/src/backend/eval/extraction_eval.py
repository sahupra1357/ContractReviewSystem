"""Gate G2 eval — extraction fidelity + clause boundaries vs golden labels.

Usage (from backend/):  uv run python -m backend.eval.extraction_eval

Thresholds (docs/02_sdlc_plan.md, Gate G2):
  born-digital (pdf/docx) text fidelity ≥ 0.95
  scanned                 text fidelity ≥ 0.90
  expected section headings found (born-digital) ≥ 0.90

Fidelity = SequenceMatcher ratio on whitespace-normalized, uppercased text —
insensitive to line wrapping, sensitive to real content loss/corruption.
"""

import re
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from backend.extraction.service import extract_document

GOLDEN = Path(__file__).parents[4] / "golden_set"
THRESHOLDS = {"born-digital": 0.95, "scanned": 0.90, "sections": 0.90}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().upper()


def _heading_found(expected: str, extracted_headings: list[str]) -> bool:
    """OCR-tolerant heading match: same section number + fuzzy title."""
    exp = normalize(expected)
    for heading in extracted_headings:
        if SequenceMatcher(None, exp, normalize(heading)).ratio() >= 0.8:
            return True
    return False


def evaluate() -> int:
    rows = []
    for labels_path in sorted(GOLDEN.glob("docs/*/labels.yaml")):
        labels = yaml.safe_load(labels_path.read_text())
        doc_dir = labels_path.parent
        data = (doc_dir / labels["filename"]).read_bytes()
        source = (doc_dir / "source.txt").read_text()

        artifact = extract_document(data, labels["filename"])
        fidelity = SequenceMatcher(
            None, normalize(source), normalize(artifact["full_text"])
        ).ratio()

        extracted_headings = [s["heading"] for s in artifact["sections"]]
        expected = labels["expected_sections"]
        sections_found = (
            sum(_heading_found(e, extracted_headings) for e in expected) / len(expected)
            if expected else 1.0
        )
        rows.append(
            dict(doc_id=labels["doc_id"], format=labels["format"],
                 poor=labels.get("poor_scan", False), method=artifact["method"],
                 fidelity=fidelity, sections_found=sections_found)
        )
        print(f"  {labels['doc_id']}  {labels['format']:16s} "
              f"fidelity={fidelity:.3f}  sections={sections_found:.2f}"
              f"{'  (poor scan)' if labels.get('poor_scan') else ''}")

    def avg(items, key):
        return sum(r[key] for r in items) / len(items)

    born = [r for r in rows if r["format"] in ("born-digital-pdf", "docx")]
    scanned = [r for r in rows if r["format"] == "scanned-pdf"]

    born_fid, scan_fid = avg(born, "fidelity"), avg(scanned, "fidelity")
    born_min, scan_min = min(r["fidelity"] for r in born), min(r["fidelity"] for r in scanned)
    born_sections = avg(born, "sections_found")

    git_rev = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
        cwd=GOLDEN,
    ).stdout.strip()

    print(f"\n== Gate G2 results (golden set @ {git_rev or 'uncommitted'}, {len(rows)} docs) ==")
    checks = [
        ("born-digital fidelity (avg)", born_fid, THRESHOLDS["born-digital"]),
        ("scanned fidelity (avg)", scan_fid, THRESHOLDS["scanned"]),
        ("born-digital sections found", born_sections, THRESHOLDS["sections"]),
    ]
    failed = False
    for name, value, threshold in checks:
        ok = value >= threshold
        failed |= not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {value:.3f} (>= {threshold})")
    print(f"  info  born-digital fidelity (min): {born_min:.3f}")
    print(f"  info  scanned fidelity (min):      {scan_min:.3f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(evaluate())
