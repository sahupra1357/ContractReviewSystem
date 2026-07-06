"""Template families — canonical source lives in the backend package
(backend.analysis.reference_templates); this shim keeps the generator
working unchanged. Requires running via `uv run` from backend/ so the
workspace package is importable."""

from backend.analysis.reference_templates import (  # noqa: F401
    FAMILIES,
    LEASE_V1,
    PURCHASE_V1,
    VENDOR_V1,
)
