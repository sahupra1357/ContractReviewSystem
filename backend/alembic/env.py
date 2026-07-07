from alembic import context
from sqlalchemy import create_engine

import backend.analysis.models  # noqa: F401
import backend.api.review  # noqa: F401  (Decision model)
import backend.audit  # noqa: F401  (register models on Base.metadata)
import backend.auth  # noqa: F401  (User model)
import backend.knowledge.models  # noqa: F401
import backend.models  # noqa: F401
import backend.pii.models  # noqa: F401
from backend.config import get_settings
from backend.db import Base, _normalize_db_url

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_normalize_db_url(get_settings().database_url),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_normalize_db_url(get_settings().database_url))
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
