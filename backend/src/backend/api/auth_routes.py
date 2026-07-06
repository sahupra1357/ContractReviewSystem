from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.audit import ActorType, record_event
from backend.auth import DbSession, authenticate, issue_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    role: str


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, session: DbSession) -> LoginResponse:
    user = authenticate(session, body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid credentials")
    record_event(
        session, actor_type=ActorType.human, actor_id=user.username,
        action="auth.login", object_type="user", object_id=user.id,
    )
    session.commit()
    return LoginResponse(token=issue_token(user), username=user.username,
                         role=user.role)
