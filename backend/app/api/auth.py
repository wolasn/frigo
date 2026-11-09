"""Inscription, connexion, déconnexion et compte courant."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.api.deps import SESSION_COOKIE, SESSION_DURATION, CurrentUser, DbSession, set_session_cookie
from app.models import AuthSession, User
from app.models.enums import UserRole
from app.security import (
    hash_password,
    hash_token,
    login_throttle,
    new_session_token,
    password_needs_rehash,
    verify_password,
)
from app.services.accounts import (
    SuperAdminCannotLeave,
    UsernameTaken,
    create_user,
    delete_account,
    find_user_by_username,
)
from app.services.planning import recompute_reservations

router = APIRouter(prefix="/api/auth", tags=["authentification"])


class RegisterIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,32}$")
    display_name: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=10, max_length=200)


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    role: UserRole

    @classmethod
    def of(cls, user: User) -> "UserOut":
        return cls(id=user.id, username=user.username, display_name=user.display_name, role=user.role)


def _open_session(session: DbSession, user: User, request: Request, response: Response) -> None:
    token = new_session_token()
    now = datetime.now(UTC)
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now + SESSION_DURATION,
            last_seen_at=now,
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        )
    )
    user.last_login_at = now
    session.commit()
    set_session_cookie(response, token)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, session: DbSession, request: Request, response: Response) -> UserOut:
    try:
        user = create_user(session, body.username, body.display_name, body.password)
    except (UsernameTaken, IntegrityError):
        # IntegrityError : deux inscriptions simultanées avec le même identifiant.
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Cet identifiant est déjà utilisé.") from None
    _open_session(session, user, request, response)
    return UserOut.of(user)


@router.post("/login")
def login(body: LoginIn, session: DbSession, request: Request, response: Response) -> UserOut:
    key = body.username.lower()
    if login_throttle.is_blocked(key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives. Réessaie dans quelques minutes.",
        )
    user = find_user_by_username(session, body.username)
    if not verify_password(user.password_hash if user else None, body.password):
        login_throttle.record_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Identifiant ou mot de passe incorrect.")

    login_throttle.reset(key)
    assert user is not None
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    _open_session(session, user, request, response)
    return UserOut.of(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    session: DbSession,
    response: Response,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    if token:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return UserOut.of(user)


class ProfileIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=60)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


class DeleteAccountIn(BaseModel):
    password: str = Field(max_length=200)


def _check_password(user: User, password: str) -> None:
    if not verify_password(user.password_hash, password):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Mot de passe actuel incorrect.")


@router.patch("/me")
def update_profile(body: ProfileIn, session: DbSession, user: CurrentUser) -> UserOut:
    user.display_name = body.display_name.strip()
    session.commit()
    return UserOut.of(user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordIn,
    session: DbSession,
    user: CurrentUser,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    """Change le mot de passe et déconnecte tous les autres appareils."""
    _check_password(user, body.current_password)
    user.password_hash = hash_password(body.new_password)
    current = hash_token(token) if token else ""
    session.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.token_hash != current))
    session.commit()


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_account(body: DeleteAccountIn, session: DbSession, user: CurrentUser, response: Response) -> None:
    _check_password(user, body.password)
    try:
        delete_account(session, user)
    except SuperAdminCannotLeave:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Le super-administrateur doit d'abord transmettre son rôle (commande super-admin --replace).",
        ) from None
    recompute_reservations(session)
    session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
