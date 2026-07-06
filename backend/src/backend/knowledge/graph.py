"""Graph-lite extraction (design §3.4) — relational graph, Neptune deferred.

Party entities come from the PII entity map placeholders and link to
pii_known_entities by MASTER ID ONLY (raw values never leave the restricted
map). Cross-contract queries — "all contracts with this party" — join on
master_entity_id. Term entities (amounts, dates, durations) are parsed from
masked text, which is PII-free by construction.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.knowledge.models import GraphEntity, GraphRelationship
from backend.models import Document
from backend.pii.models import EntityMapRow, KnownEntity

_TERM_PATTERNS = {
    "amount": re.compile(r"\bUSD [\d,]+\b"),
    "duration_months": re.compile(r"\b(\d{1,3}) months?\b"),
    "date": re.compile(r"\b20\d{2}-\d{2}-\d{2}\b"),
}


def rebuild_graph(session: Session, document: Document, masked_text: str) -> int:
    """Idempotent: wipes and rebuilds this document's entities/relationships."""
    for table in (GraphRelationship, GraphEntity):
        for row in session.execute(
            select(table).where(table.document_id == document.id)
        ).scalars():
            session.delete(row)
    session.flush()

    contract = GraphEntity(
        document_id=document.id, kind="contract", ref=document.id, entity_type=None
    )
    session.add(contract)
    session.flush()

    count = 0
    # parties: placeholders from the entity map, linked by master id
    for row in session.execute(
        select(EntityMapRow).where(EntityMapRow.document_id == document.id)
    ).scalars():
        if row.entity_type not in ("ORG", "PERSON"):
            continue
        master = session.execute(
            select(KnownEntity).where(KnownEntity.value == row.entity_value)
        ).scalar_one_or_none()
        entity = GraphEntity(
            document_id=document.id,
            kind="party",
            ref=row.placeholder,
            entity_type=row.entity_type,
            master_entity_id=master.id if master else None,
        )
        session.add(entity)
        session.flush()
        session.add(GraphRelationship(
            document_id=document.id, from_entity_id=contract.id,
            rel_type="HAS_PARTY", to_entity_id=entity.id,
        ))
        count += 1

    # terms from masked (PII-free) text
    for kind, pattern in _TERM_PATTERNS.items():
        for value in dict.fromkeys(pattern.findall(masked_text)):
            entity = GraphEntity(
                document_id=document.id, kind="term", ref=value, entity_type=kind
            )
            session.add(entity)
            session.flush()
            session.add(GraphRelationship(
                document_id=document.id, from_entity_id=contract.id,
                rel_type="HAS_TERM", to_entity_id=entity.id,
            ))
            count += 1
    return count
