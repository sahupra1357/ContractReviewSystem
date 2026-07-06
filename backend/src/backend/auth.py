"""Authentication & RBAC (design §3.6) — the Cognito-shaped seam.

POC: users in Postgres (pbkdf2 password hashes), JWT bearer tokens signed
with CRS_JWT_SECRET. Production swaps token issuance/validation for Cognito;
`get_actor` is the single dependency every API imports, so the swap touches
one module. This replaces the Phase-1 X-Actor-Id header placeholder.
"""

import enum
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from backend.config import get_settings
from backend.db import Base, get_db

_ALGO = "HS256"
_TOKEN_TTL = timedelta(hours=12)
_PBKDF2_ITERATIONS = 200_000


class Role(enum.StrEnum):
    reviewer = "reviewer"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


@dataclass
class Actor:
    user_id: str
    username: str
    role: str


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, _digest = stored.split("$", 1)
    return secrets.compare_digest(hash_password(password, salt), stored)


def issue_token(user: User) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": user.id, "username": user.username, "role": user.role,
         "iat": now, "exp": now + _TOKEN_TTL},
        get_settings().jwt_secret,
        algorithm=_ALGO,
    )


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def get_actor(authorization: str | None = Header(default=None)) -> Actor:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="bearer token required")
    try:
        payload = jwt.decode(
            authorization.removeprefix("Bearer "),
            get_settings().jwt_secret,
            algorithms=[_ALGO],
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from exc
    return Actor(user_id=payload["sub"], username=payload["username"],
                 role=payload["role"])


def require_role(role: Role):
    def dependency(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
        if actor.role != role:
            raise HTTPException(status_code=403, detail=f"{role} role required")
        return actor

    return dependency


require_reviewer = require_role(Role.reviewer)
require_admin = require_role(Role.admin)


def seed_users(session: Session, users: list[tuple[str, str, str]]) -> int:
    """[(username, password, role)] — idempotent; returns number created."""
    existing = {u.username for u in session.execute(select(User)).scalars()}
    created = 0
    for username, password, role in users:
        if username not in existing:
            session.add(User(username=username,
                             password_hash=hash_password(password), role=role))
            created += 1
    return created


# imported for typing convenience by API modules
DbSession = Annotated[Session, Depends(get_db)]
CurrentActor = Annotated[Actor, Depends(get_actor)]
ReviewerActor = Annotated[Actor, Depends(require_reviewer)]
AdminActor = Annotated[Actor, Depends(require_admin)]
