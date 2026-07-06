"""Source connector interface (design doc §3.1).

POC ships the upload path only (a push-based API route — see api/ingest.py).
Pull-based sources (DMS, shared filesystem, SharePoint, DocuSign, Email)
implement SourceConnector and plug in with zero changes to the ingestion
core: a runner polls, fetches, hands bytes to ingest_document(), and acks.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceDocument:
    """A document as announced by a source, before fetching its bytes."""

    ref: str  # source-native identifier (path, envelope id, message id…)
    filename: str
    metadata: dict[str, Any] = field(default_factory=dict)


class SourceConnector(ABC):
    """Pull-based source plug-in. Credentials come from configuration
    (Secrets Manager in production) — never hardcoded."""

    name: str  # e.g. "dms", "sharepoint" — recorded as documents.source

    @abstractmethod
    def poll(self) -> list[SourceDocument]:
        """List documents not yet acked, oldest first."""

    @abstractmethod
    def fetch(self, ref: str) -> tuple[bytes, str | None]:
        """Return (content bytes, content_type) for a source document."""

    @abstractmethod
    def ack(self, ref: str) -> None:
        """Mark a source document consumed so poll() stops returning it."""
