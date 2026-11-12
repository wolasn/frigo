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
    photo_local_fallback: bool
    ai_recipe_model: Literal["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]


class SettingsIn(BaseModel):
    photo_engine: Literal["claude", "local"] | None = None
    photo_local_url: str | None = Field(default=None, max_length=200, pattern=r"^https?://")
    photo_local_model: str | None = Field(default=None, min_length=1, max_length=100)
    photo_local_fallback: bool | None = None
    ai_recipe_model: Literal["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"] | None = None


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


# ---------- Coûts de l'IA ----------


class UsageTotals(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class UserUsage(UsageTotals):
    user_id: str | None  # vide : compte supprimé
    username: str
    display_name: str | None
    recipes: UsageTotals
    photos: UsageTotals


class UsageOut(BaseModel):
    month: str | None  # AAAA-MM, vide = depuis le début
    total: UsageTotals
    users: list[UserUsage]


class UsageCall(BaseModel):
    created_at: str
    kind: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _period(month: str | None):
    from datetime import UTC, datetime

    from app.models import AiUsage

    if not month:
        return True
    try:
        start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Mois attendu au format AAAA-MM.") from None
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return (AiUsage.created_at >= start) & (AiUsage.created_at < end)


def _totals(rows) -> UsageTotals:
    return UsageTotals(calls=sum(r[0] for r in rows), input_tokens=sum(r[1] for r in rows),
                       output_tokens=sum(r[2] for r in rows), cost_usd=round(sum(float(r[3]) for r in rows), 6))


@router.get("/ai-usage")
def ai_usage(session: DbSession, user: CurrentUser, month: str | None = None) -> UsageOut:
    """Coût de l'IA par utilisateur (total et par type d'appel), pour un mois ou depuis le début."""
    from sqlalchemy import func, select

    from app.models import AiUsage, User

    _require_super_admin(user)
    rows = session.execute(
        select(AiUsage.user_id, AiUsage.username, AiUsage.kind, func.count(), func.sum(AiUsage.input_tokens),
               func.sum(AiUsage.output_tokens), func.sum(AiUsage.cost_usd))
        .where(_period(month)).group_by(AiUsage.user_id, AiUsage.username, AiUsage.kind)
    ).all()
    names = dict(session.execute(select(User.id, User.display_name).where(
        User.id.in_({r[0] for r in rows if r[0]}))).all())
    by_user: dict = {}
    for user_id, username, kind, calls, tokens_in, tokens_out, cost in rows:
        key = str(user_id) if user_id else f"supprimé:{username}"
        by_user.setdefault(key, {"user_id": str(user_id) if user_id else None, "username": username,
                                 "display_name": names.get(user_id), "recipe": [], "photo": []})
        by_user[key][kind].append((calls, tokens_in or 0, tokens_out or 0, cost or 0))
    users = []
    for entry in by_user.values():
        both = entry["recipe"] + entry["photo"]
        users.append(UserUsage(user_id=entry["user_id"], username=entry["username"], display_name=entry["display_name"],
                               recipes=_totals(entry["recipe"]), photos=_totals(entry["photo"]), **_totals(both).model_dump()))
    users.sort(key=lambda u: -u.cost_usd)
    all_rows = [(r[3], r[4] or 0, r[5] or 0, r[6] or 0) for r in rows]
    return UsageOut(month=month, total=_totals(all_rows), users=users)


@router.get("/ai-usage/{user_id}")
def ai_usage_detail(user_id: str, session: DbSession, user: CurrentUser, month: str | None = None) -> list[UsageCall]:
    """Détail des appels d'un utilisateur (les plus récents d'abord, 500 au plus). « supprimé:nom » pour un compte supprimé."""
    import uuid

    from sqlalchemy import select

    from app.models import AiUsage

    _require_super_admin(user)
    if user_id.startswith("supprimé:"):
        who = AiUsage.user_id.is_(None) & (AiUsage.username == user_id.removeprefix("supprimé:"))
    else:
        try:
            who = AiUsage.user_id == uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable.") from None
    calls = session.scalars(select(AiUsage).where(who, _period(month)).order_by(AiUsage.created_at.desc()).limit(500))
    return [UsageCall(created_at=c.created_at.isoformat(timespec="seconds"), kind=c.kind, model=c.model,
                      input_tokens=c.input_tokens, output_tokens=c.output_tokens, cost_usd=float(c.cost_usd)) for c in calls]
