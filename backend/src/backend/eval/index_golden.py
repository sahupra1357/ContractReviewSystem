"""Drive the full golden corpus through the REAL pipeline into the index.

Usage (from backend/, compose stack up):
    CRS_DATABASE_URL=postgresql+psycopg://crs:crs@localhost:5433/crs \
        uv run python -m backend.eval.index_golden

Seeds the master table with registered AND novel golden entities (so no doc
halts — hold behavior is proven separately by pii_eval and G3), then runs
ingest → extract → mask → index in-process with BGE-M3 embeddings against
the compose Postgres/MinIO/Presidio.
"""

import sys
import time

import yaml
from sqlalchemy import select

from backend import jobs
from backend.db import get_sessionmaker
from backend.eval.extraction_eval import GOLDEN
from backend.ingestion.core import ingest_document
from backend.models import Document
from backend.pii.models import HoldStatus, PiiHold
from backend.pii.seed import seed
from backend.storage import S3MaskedStorage, S3RawStorage
from backend.worker import process_one


def _seed_novel(sessionmaker) -> int:
    from backend.pii.models import KnownEntity

    added = 0
    with sessionmaker() as session:
        from sqlalchemy import select

        existing = {e.value for e in session.execute(select(KnownEntity)).scalars()}
        for labels_path in GOLDEN.glob("docs/*/labels.yaml"):
            labels = yaml.safe_load(labels_path.read_text())
            for p in labels["pii"]:
                if not p["registered"] and p["text"] not in existing:
                    session.add(KnownEntity(
                        value=p["text"], entity_type=p["type"],
                        created_by="index-golden-eval",
                    ))
                    existing.add(p["text"])
                    added += 1
        session.commit()
    return added


def main() -> int:
    added, skipped = seed(GOLDEN / "master_table_seed.yaml", actor_id="index-golden-eval")
    sessionmaker = get_sessionmaker()
    novel_added = _seed_novel(sessionmaker)
    print(f"master table: +{added} registered (skipped {skipped}), +{novel_added} novel")

    raw, masked = S3RawStorage(), S3MaskedStorage()
    started = time.time()
    for labels_path in sorted(GOLDEN.glob("docs/*/labels.yaml")):
        labels = yaml.safe_load(labels_path.read_text())
        data = (labels_path.parent / labels["filename"]).read_bytes()
        suffix = labels["filename"].rsplit(".", 1)[1]
        with sessionmaker() as session:
            result = ingest_document(
                session, raw, source="upload",
                filename=f"{labels['doc_id']}.{suffix}", data=data,
                actor_id="index-golden-eval",
            )
            session.commit()
            if result.duplicate:
                print(f"  {labels['doc_id']}  already ingested")

    # drain all stages; resolve tripwire holds the way a human would
    # (dismiss OCR-noise false positives with a rationale, re-mask)
    dismissed_total = 0
    for _round in range(5):
        worked = False
        for stage in ("extract", "mask", "index"):
            while True:
                with sessionmaker() as session:
                    if not process_one(session, raw, masked, stage=stage):
                        break
                    worked = True
        with sessionmaker() as session:
            held = list(session.execute(
                select(Document).where(Document.status == "pii_hold")
            ).scalars())
            for doc in held:
                for hold in session.execute(
                    select(PiiHold).where(
                        PiiHold.document_id == doc.id,
                        PiiHold.status == HoldStatus.open,
                    )
                ).scalars():
                    hold.status = HoldStatus.dismissed
                    hold.rationale = (
                        "eval human-in-the-loop: OCR-noise false positive "
                        f"(span {hold.span_text[:40]!r}); all real golden "
                        "entities are registered"
                    )
                    hold.resolved_by = "index-golden-eval"
                    dismissed_total += 1
                jobs.enqueue(session, document_id=doc.id, stage="mask")
                print(f"  hold on {doc.filename}: dismissed OCR-noise flags, re-masking")
                worked = True
            session.commit()
        if not worked:
            break

    with sessionmaker() as session:
        rows = session.execute(
            select(Document.filename, Document.status).order_by(Document.filename)
        ).all()
    not_indexed = [(f, s) for f, s in rows if s != "indexed"]
    print(f"\nindexed {len(rows) - len(not_indexed)}/{len(rows)} docs "
          f"in {time.time() - started:.1f}s; holds dismissed: {dismissed_total}")
    if not_indexed:
        print(f"FAIL — not indexed: {not_indexed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
