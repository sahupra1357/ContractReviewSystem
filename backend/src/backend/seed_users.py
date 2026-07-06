"""Seed demo users (POC only — production auth is Cognito).

Usage: uv run python -m backend.seed_users
Passwords come from CRS_DEMO_PASSWORD (default "demo1234" — POC only).
"""

import os

from backend.audit import ActorType, record_event
from backend.auth import seed_users
from backend.db import get_sessionmaker

USERS = [("reviewer1", "reviewer"), ("reviewer2", "reviewer"), ("admin1", "admin")]

if __name__ == "__main__":
    password = os.environ.get("CRS_DEMO_PASSWORD", "demo1234")
    with get_sessionmaker()() as session:
        created = seed_users(session, [(u, password, r) for u, r in USERS])
        for username, role in USERS:
            record_event(
                session, actor_type=ActorType.system, actor_id="seed-users",
                action="user.seeded", object_type="user", object_id=username,
                detail={"role": role},
            )
        session.commit()
    print(f"users: {created} created ({', '.join(u for u, _ in USERS)}); "
          f"password from CRS_DEMO_PASSWORD")
