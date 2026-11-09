"""Alerte le super-administrateur quand l'IA est bloquée par le compte API (clé expirée ou révoquée,
crédit épuisé, accès refusé, clé absente) : e-mail + notification dans l'application.

Une seule alerte par type de problème et par 24 h, pour ne pas inonder sa boîte au fil des
tentatives des utilisateurs. L'horodatage est gardé dans le volume d'état.
"""

import json
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.mailer import MailError, MailNotConfigured, send_admin_email
from app.models import Notification, User
from app.models.enums import NotificationType, UserRole
from app.services.ai_recipes import AiError

logger = logging.getLogger("frigo.ai")

ALERT_EVERY = timedelta(hours=24)
SUBJECTS = {
    "key": "Clé d'API Claude refusée (expirée ou révoquée ?)",
    "credit": "Compte API Claude sans crédit",
    "access": "Clé d'API Claude sans accès au modèle",
    "not_configured": "Clé d'API Claude absente",
}


def _state_file() -> Path:
    return Path(os.environ.get("STATE_DIR", "/app/state")) / "ai_alerts.json"


def alert_admin(
    session: Session,
    error: AiError,
    send: Callable[[str, str], None] | None = None,
    now: datetime | None = None,
) -> bool:
    """Prévient le super-administrateur si besoin. Renvoie True si une alerte est partie."""
    if not error.needs_admin:
        return False
    send = send or send_admin_email
    now = now or datetime.now(UTC)
    path = _state_file()
    try:
        sent = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        sent = {}
    last = sent.get(error.kind)
    if last and now - datetime.fromisoformat(last) < ALERT_EVERY:
        return False

    subject = SUBJECTS.get(error.kind, "Recettes IA indisponibles")
    body = (f"Les recettes IA sont bloquées depuis {now.isoformat(timespec='minutes')} (UTC).\n\n{error}\n\n"
            "Les utilisateurs voient « Les recettes IA sont momentanément indisponibles ». "
            "Cette alerte ne sera pas renvoyée avant 24 h.")
    try:
        send(subject, body)
    except (MailNotConfigured, MailError) as mail_error:
        logger.warning("Alerte IA non envoyée par e-mail : %s", mail_error)

    admin = session.scalar(select(User).where(User.role == UserRole.SUPER_ADMIN))
    if admin is not None:
        session.add(Notification(user_id=admin.id, type=NotificationType.SYSTEM, created_at=now,
                                 payload={"message": f"{subject} : {error}"}))
        session.commit()

    sent[error.kind] = now.isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sent), encoding="utf-8")
    return True
