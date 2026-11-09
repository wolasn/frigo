"""Dépendances communes : utilisateur connecté à partir du cookie de session."""

import os
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AuthSession, User
from app.security import hash_token

SESSION_COOKIE = "frigo_session"
SESSION_DURATION = timedelta(days=30)
# La session est prolongée au plus une fois par heure d'utilisation.
SESSION_REFRESH_AFTER = timedelta(hours=1)
# Cookie « Secure » (HTTPS seulement) : à activer en production derrière Caddy.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

DbSession = Annotated[Session, Depends(get_session)]


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_DURATION.total_seconds()),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def get_current_user(
    session: DbSession,
    response: Response,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Connexion requise.")
    if not token:
        raise unauthorized

    now = datetime.now(UTC)
    row = session.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(AuthSession.token_hash == hash_token(token), AuthSession.expires_at > now)
    ).first()
    if row is None:
        raise unauthorized

    auth_session, user = row
    if now - auth_session.last_seen_at > SESSION_REFRESH_AFTER:
        auth_session.last_seen_at = now
        auth_session.expires_at = now + SESSION_DURATION
        session.commit()
        set_session_cookie(response, token)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
