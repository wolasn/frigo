"""Inscription, connexion, déconnexion et compte courant."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import SESSION_COOKIE, SESSION_DURATION, CurrentUser, DbSession, set_session_cookie
from app.models import AuthSession, SignupInvitation, User
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

router = APIRouter(prefix="/api/auth", tags=["authentification"])

# Appli privée : on ne s'inscrit qu'avec un lien créé par un membre, valable 10 minutes et une seule fois.
# Seul le tout premier compte (base vide) s'inscrit sans lien. Désactivable pour les tests.
INVITE_REQUIRED = os.environ.get("SIGNUP_INVITE_REQUIRED", "true").lower() == "true"
INVITE_DURATION = timedelta(minutes=10)
MAX_ACTIVE_INVITES = 5  # liens encore valables par membre
INVALID_INVITE = "Ce lien d'inscription n'est plus valable (déjà utilisé ou expiré) : demande-en un nouveau."


class RegisterIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,32}$")
    display_name: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=10, max_length=200)
    invitation: str | None = Field(default=None, max_length=100)


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
    invitation = None
    if INVITE_REQUIRED and session.scalar(select(func.count()).select_from(User)) > 0:
        # verrou : deux inscriptions simultanées ne peuvent pas utiliser le même lien
        invitation = session.scalar(select(SignupInvitation).where(
            SignupInvitation.token_hash == hash_token(body.invitation or "")).with_for_update())
        if invitation is None or invitation.used_at is not None or invitation.expires_at <= datetime.now(UTC):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=INVALID_INVITE)
    try:
        user = create_user(session, body.username, body.display_name, body.password)
    except (UsernameTaken, IntegrityError):
        # IntegrityError : deux inscriptions simultanées avec le même identifiant.
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Cet identifiant est déjà utilisé.") from None
    if invitation is not None:
        invitation.used_at, invitation.used_by = datetime.now(UTC), user.id
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
    session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


# ---------- Liens d'inscription ----------


class InvitationOut(BaseModel):
    code: str  # à mettre dans le lien ; jamais stocké en clair
    expires_at: datetime


class InvitationCheck(BaseModel):
    valid: bool
    required: bool
    expires_at: datetime | None = None


@router.post("/invitations", status_code=status.HTTP_201_CREATED)
def create_invitation(session: DbSession, user: CurrentUser) -> InvitationOut:
    """Nouveau lien d'inscription : une seule utilisation, valable 10 minutes."""
    now = datetime.now(UTC)
    active = session.scalar(select(func.count()).select_from(SignupInvitation).where(
        SignupInvitation.created_by == user.id, SignupInvitation.used_at.is_(None), SignupInvitation.expires_at > now))
    if active >= MAX_ACTIVE_INVITES:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=f"Déjà {MAX_ACTIVE_INVITES} liens en cours : attends qu'ils expirent (10 minutes).")
    code = new_session_token()
    invitation = SignupInvitation(token_hash=hash_token(code), created_by=user.id, expires_at=now + INVITE_DURATION)
    session.add(invitation)
    session.commit()
    return InvitationOut(code=code, expires_at=invitation.expires_at)


@router.get("/invitations/check")
def check_invitation(session: DbSession, code: str = "") -> InvitationCheck:
    """La page d'inscription vérifie le lien avant d'afficher le formulaire."""
    if not INVITE_REQUIRED or session.scalar(select(func.count()).select_from(User)) == 0:
        return InvitationCheck(valid=True, required=False)
    invitation = session.scalar(select(SignupInvitation).where(SignupInvitation.token_hash == hash_token(code[:100])))
    valid = invitation is not None and invitation.used_at is None and invitation.expires_at > datetime.now(UTC)
    return InvitationCheck(valid=valid, required=True, expires_at=invitation.expires_at if valid else None)
