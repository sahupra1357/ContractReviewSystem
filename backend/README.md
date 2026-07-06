# Contract Review Co-Pilot — Backend

FastAPI application and document pipeline. See the repo root `CLAUDE.md` for
commands and `docs/03_design_document.md` for the authoritative design.

- `src/backend/config.py` — settings (env prefix `CRS_`)
- `src/backend/main.py` — FastAPI app
- `src/backend/db.py` — SQLAlchemy base/session
- `src/backend/audit.py` — append-only audit writer (SOX-aware core)
- `alembic/` — migrations (run automatically on container boot)
- `tests/` — pytest; `tests/invariants/` requires the compose Postgres
