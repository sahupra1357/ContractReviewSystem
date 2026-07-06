"""Seed the PII master table from a YAML file (types → list of values).

Usage (from backend/):
    uv run python -m backend.pii.seed ../golden_set/master_table_seed.yaml

Idempotent: existing values are skipped. Every insert is audited — the
master table is a controlled security artifact, even when seeded by script.
"""

import sys
from pathlib import Path

import yaml
from sqlalchemy import select

from backend.audit import ActorType, record_event
from backend.db import get_sessionmaker
from backend.pii.models import KnownEntity

_TYPE_MAP = {"org": "ORG", "person": "PERSON", "account": "ACCOUNT", "address": "ADDRESS"}


def seed(path: Path, actor_id: str = "seed-script") -> tuple[int, int]:
    data = yaml.safe_load(path.read_text())
    added = skipped = 0
    with get_sessionmaker()() as session:
        existing = {
            e.value for e in session.execute(select(KnownEntity)).scalars()
        }
        for type_key, values in data.items():
            entity_type = _TYPE_MAP.get(type_key, type_key.upper())
            for value in values:
                if value in existing:
                    skipped += 1
                    continue
                entity = KnownEntity(
                    value=value, entity_type=entity_type, created_by=actor_id
                )
                session.add(entity)
                session.flush()
                record_event(
                    session,
                    actor_type=ActorType.human,
                    actor_id=actor_id,
                    action="pii_master.added",
                    object_type="pii_known_entity",
                    object_id=entity.id,
                    detail={"entity_type": entity_type},
                )
                added += 1
        session.commit()
    return added, skipped


if __name__ == "__main__":
    added, skipped = seed(Path(sys.argv[1]))
    print(f"master table: {added} added, {skipped} already present")
