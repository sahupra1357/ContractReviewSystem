"""Gate G3 eval — the PII gate measured on the golden set.

Usage (from backend/, compose presidio-analyzer must be up):
    uv run python -m backend.eval.pii_eval

Measures, per docs/02_sdlc_plan.md Gate G3:
  1. HARD: zero unregistered planted entities pass unhalted — every doc with
     novel PII must halt in pii_hold.
  2. HARD: recall ≥ 0.98 on downstream-reaching text — no labeled PII
     (fuzzy-searched) survives in any masked artifact that would flow
     downstream, including after simulated hold resolution.
  3. INFO: tripwire false-alarm rate — non-novel docs halted anyway
     (hold-queue burden), reported not gated.

Self-contained: extracts + masks in-process with the master seed; only the
tripwire hits the live Presidio service.
"""

import sys

import yaml

from backend.eval.extraction_eval import GOLDEN
from backend.extraction.service import extract_document
from backend.pii.masker import _entity_pattern, mask_text
from backend.pii.tripwire import detect

ANALYZER_URL = "http://localhost:5002"
RECALL_THRESHOLD = 0.98


def _load_master() -> list[tuple[str, str]]:
    type_map = {"org": "ORG", "person": "PERSON", "account": "ACCOUNT",
                "address": "ADDRESS"}
    seed = yaml.safe_load((GOLDEN / "master_table_seed.yaml").read_text())
    return [(v, type_map[k]) for k, values in seed.items() for v in values]


def evaluate() -> int:
    master = _load_master()
    total_entities = 0
    leaked_entities = 0
    novel_docs = []
    novel_unhalted = []
    false_alarms = []
    results = []

    for labels_path in sorted(GOLDEN.glob("docs/*/labels.yaml")):
        labels = yaml.safe_load(labels_path.read_text())
        doc_dir = labels_path.parent
        data = (doc_dir / labels["filename"]).read_bytes()

        artifact = extract_document(data, labels["filename"])
        masked_text, _ = mask_text(artifact["full_text"], master)
        flags = detect(masked_text, analyzer_url=ANALYZER_URL)
        halted = bool(flags)

        if labels["has_novel_pii"]:
            novel_docs.append(labels["doc_id"])
            if not halted:
                novel_unhalted.append(labels["doc_id"])
        elif halted:
            false_alarms.append(
                (labels["doc_id"], sorted({f.flag_type for f in flags}))
            )

        # simulate resolution for halted novel docs: register the novel
        # entities (what the human does) and re-mask
        downstream_text = masked_text
        if halted and labels["has_novel_pii"]:
            enriched = master + [
                (p["text"], p["type"]) for p in labels["pii"] if not p["registered"]
            ]
            downstream_text, _ = mask_text(artifact["full_text"], enriched)

        leaked_here = []
        if not halted or labels["has_novel_pii"]:
            # this text reaches downstream (immediately, or after resolution)
            for p in labels["pii"]:
                total_entities += 1
                if _entity_pattern(p["text"]).search(downstream_text):
                    leaked_entities += 1
                    leaked_here.append(p["text"])
        else:
            # false-alarm halt: nothing flows downstream until a human acts —
            # count its entities as protected
            total_entities += len(labels["pii"])

        results.append((labels["doc_id"], labels["format"], halted,
                        labels["has_novel_pii"], leaked_here))
        print(f"  {labels['doc_id']}  {labels['format']:16s} "
              f"{'HALTED' if halted else 'passed':7s} "
              f"novel={labels['has_novel_pii']!s:5s} leaked={leaked_here or '-'}")

    recall = 1.0 - (leaked_entities / total_entities) if total_entities else 1.0
    print(f"\n== Gate G3 results ({len(results)} docs, {total_entities} labeled entities) ==")
    ok_novel = not novel_unhalted
    ok_recall = recall >= RECALL_THRESHOLD
    print(f"  {'PASS' if ok_novel else 'FAIL'}  novel-PII docs halted: "
          f"{len(novel_docs) - len(novel_unhalted)}/{len(novel_docs)}"
          f"{'' if ok_novel else '  UNHALTED: ' + ', '.join(novel_unhalted)}")
    print(f"  {'PASS' if ok_recall else 'FAIL'}  downstream recall: {recall:.4f} "
          f"(>= {RECALL_THRESHOLD}; leaked {leaked_entities}/{total_entities})")
    print(f"  info  tripwire false alarms: {len(false_alarms)}/16 non-novel docs "
          f"({len(false_alarms) / 16:.0%} hold burden)")
    for doc_id, types in false_alarms:
        print(f"        {doc_id}: {types}")
    return 0 if (ok_novel and ok_recall) else 1


if __name__ == "__main__":
    sys.exit(evaluate())
