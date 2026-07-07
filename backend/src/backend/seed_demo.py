"""One-command demo seeding — SYNTHETIC DATA ONLY.

Usage (locally from backend/, or in a Render shell on the web service):
    python -m backend.seed_demo

Seeds demo users, the PII master table, and ingests the packaged synthetic
golden corpus (22 contracts). The pipeline worker processes them from there.
Idempotent: duplicates are skipped by content hash.

POLICY: this deployment mode is for the C-level demo with the synthetic
corpus. Never upload real contracts to a PaaS-hosted instance — production
is the in-VPC AWS build (design doc §7).
"""

import os
from pathlib import Path

import yaml

from backend.audit import ActorType, record_event
from backend.auth import seed_users
from backend.db import get_sessionmaker
from backend.ingestion.core import ingest_document
from backend.pii.models import KnownEntity
from backend.storage import S3RawStorage

# packaged into the container image (backend/Dockerfile); repo path locally
_CANDIDATES = [Path("/app/golden_set"), Path(__file__).parents[3] / "golden_set"]

USERS = [("reviewer1", "reviewer"), ("reviewer2", "reviewer"), ("admin1", "admin")]
_TYPE_MAP = {"org": "ORG", "person": "PERSON", "account": "ACCOUNT", "address": "ADDRESS"}


def main() -> None:
    golden = next((p for p in _CANDIDATES if p.is_dir()), None)
    if golden is None:
        raise SystemExit(f"golden_set not found in {_CANDIDATES}")
    password = os.environ.get("CRS_DEMO_PASSWORD", "demo1234")

    sessionmaker = get_sessionmaker()
    with sessionmaker() as session:
        created = seed_users(session, [(u, password, r) for u, r in USERS])
        session.commit()
    print(f"users: {created} created")

    with sessionmaker() as session:
        from sqlalchemy import select

        existing = {e.value for e in session.execute(select(KnownEntity)).scalars()}
        seed = yaml.safe_load((golden / "master_table_seed.yaml").read_text())
        added = 0
        for type_key, values in seed.items():
            for value in values:
                if value in existing:
                    continue
                entity = KnownEntity(value=value, entity_type=_TYPE_MAP[type_key],
                                     created_by="seed-demo")
                session.add(entity)
                session.flush()
                record_event(
                    session, actor_type=ActorType.system, actor_id="seed-demo",
                    action="pii_master.added", object_type="pii_known_entity",
                    object_id=entity.id, detail={"entity_type": entity.entity_type},
                )
                added += 1
        session.commit()
    print(f"master table: {added} entities added")

    raw = S3RawStorage()
    landed = duplicates = 0
    for labels_path in sorted(golden.glob("docs/*/labels.yaml")):
        labels = yaml.safe_load(labels_path.read_text())
        data = (labels_path.parent / labels["filename"]).read_bytes()
        suffix = labels["filename"].rsplit(".", 1)[1]
        with sessionmaker() as session:
            result = ingest_document(
                session, raw, source="upload",
                filename=f"{labels['doc_id']}.{suffix}", data=data,
                actor_id="seed-demo",
            )
            session.commit()
        duplicates += result.duplicate
        landed += not result.duplicate
    print(f"corpus: {landed} contracts landed, {duplicates} already present")
    print("The worker will process them (watch the dashboard). Note: docs with "
          "novel PII will halt in pii_hold — resolve them in PII Admin (that's "
          "the demo).")


if __name__ == "__main__":
    main()
