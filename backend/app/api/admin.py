"""Statut de la base pour le super-administrateur.

- /api/admin/status : protégé par la clé de la page de statut (secret status_page_key),
  utilisable même quand la base est bloquée et que personne ne peut se connecter ;
- /api/admin/db-status et /api/admin/check-now : réservés au super-administrateur connecté.
"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from app.api.deps import CurrentUser
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
