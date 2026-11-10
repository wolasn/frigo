"""Statut de la base pour le super-administrateur.

- /api/admin/status : protégé par la clé de la page de statut (secret status_page_key),
  utilisable même quand la base est bloquée et que personne ne peut se connecter ;
- /api/admin/db-status et /api/admin/check-now : réservés au super-administrateur connecté.
"""

import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.db import check_database
from app.models.enums import UserRole
from app.monitoring import read_status, run_check
from app.secrets import read_secret

router = APIRouter(prefix="/api/admin", tags=["administration"])


class StatusOut(BaseModel):
    status: str
    cause: str | None
    since: str | None
    last_check: str | None
    last_incident_start: str | None
    last_incident_end: str | None
    email_error: str | None
    live: str | None = None  # résultat d'une vérification immédiate


def _require_super_admin(user) -> None:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Réservé au super-administrateur.")


@router.get("/status")
def status_with_key(x_status_key: Annotated[str | None, Header()] = None) -> StatusOut:
    expected = read_secret("status_page_key")
    if not expected:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Page de statut désactivée.")
    if not x_status_key or not hmac.compare_digest(x_status_key.encode(), expected.encode()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Clé incorrecte.")
    live, _detail = check_database()
    return StatusOut(**vars(read_status()), live=live)


@router.get("/db-status")
def db_status(user: CurrentUser) -> StatusOut:
    _require_super_admin(user)
    return StatusOut(**vars(read_status()))


@router.post("/check-now")
def check_now(user: CurrentUser) -> StatusOut:
    _require_super_admin(user)
    return StatusOut(**vars(run_check(retries=1)))


class SettingsOut(BaseModel):
    photo_engine: Literal["claude", "local"]
    photo_local_url: str
    photo_local_model: str


class SettingsIn(BaseModel):
    photo_engine: Literal["claude", "local"] | None = None
    photo_local_url: str | None = Field(default=None, max_length=200, pattern=r"^https?://")
    photo_local_model: str | None = Field(default=None, min_length=1, max_length=100)


def _settings(session) -> SettingsOut:
    from app.services.settings import get_setting

    return SettingsOut(**{key: get_setting(session, key) for key in SettingsOut.model_fields})


@router.get("/settings")
def read_settings(session: DbSession, user: CurrentUser) -> SettingsOut:
    """Paramètres globaux : mode d'analyse photo appliqué à tout le monde."""
    _require_super_admin(user)
    return _settings(session)


@router.patch("/settings")
def update_settings(body: SettingsIn, session: DbSession, user: CurrentUser) -> SettingsOut:
    from app.services.settings import set_setting

    _require_super_admin(user)
    for key, value in body.model_dump(exclude_none=True).items():
        set_setting(session, key, value.strip() if isinstance(value, str) else value, user.id)
    session.commit()
    return _settings(session)
