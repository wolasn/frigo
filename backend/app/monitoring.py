"""Surveillance de la base : vérification du matin, état conservé hors de la base, alertes e-mail.

L'état est écrit dans un fichier (volume Docker) : quand la base est bloquée, c'est le
seul endroit où le noter. Un e-mail part au passage « disponible → bloquée », un autre
au retour à la normale ; une vérification qui échoue encore n'en renvoie pas.
"""

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.db import check_database
from app.mailer import MailError, MailNotConfigured, send_admin_email

logger = logging.getLogger("frigo.monitoring")

STATE_FILE = Path(os.environ.get("STATE_DIR", "/app/state")) / "db_status.json"
RETRIES = 3
RETRY_DELAY_SECONDS = 180


@dataclass
class DbStatus:
    status: str = "unknown"  # ok | down | unknown
    cause: str | None = None
    since: str | None = None  # début de l'état actuel (ISO 8601)
    last_check: str | None = None
    last_incident_start: str | None = None
    last_incident_end: str | None = None
    email_error: str | None = None


def read_status(path: Path = STATE_FILE) -> DbStatus:
    try:
        return DbStatus(**json.loads(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return DbStatus()


def _write(status: DbStatus, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(status), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _describe(state: str, detail: str | None) -> str:
    if state == "non_configuree":
        return "secret database_url absent"
    return f"base injoignable ({detail or 'erreur inconnue'}) : projet Supabase en pause, réseau ou identifiants"


def run_check(
    check: Callable[[], tuple[str, str | None]] = check_database,
    send: Callable[[str, str], None] = send_admin_email,
    path: Path = STATE_FILE,
    retries: int = RETRIES,
    delay: float = RETRY_DELAY_SECONDS,
) -> DbStatus:
    """Vérifie la base (avec nouvelles tentatives), met à jour l'état et prévient si besoin."""
    state, detail = check()
    attempt = 1
    while state != "ok" and attempt < retries:
        time.sleep(delay)
        state, detail = check()
        attempt += 1

    now = datetime.now(UTC).isoformat(timespec="seconds")
    status = read_status(path)
    status.last_check = now
    previous = status.status

    if state == "ok":
        if previous == "down":
            status.last_incident_end = now
            _try_send(status, send, "Base de données de nouveau disponible",
                      f"La base répond de nouveau depuis {now} (UTC).\n"
                      f"Elle était indisponible depuis {status.since} : {status.cause}.")
        if previous != "ok":
            status.since = now
        status.status, status.cause = "ok", None
    else:
        cause = _describe(state, detail)
        if previous != "down":
            status.status, status.since, status.cause = "down", now, cause
            status.last_incident_start, status.last_incident_end = now, None
            _try_send(status, send, "Base de données indisponible",
                      f"La vérification du matin a échoué {retries} fois ({now}, UTC).\n"
                      f"Cause : {cause}.\n\n"
                      "Les utilisateurs voient « Service momentanément indisponible ».\n"
                      "Si le projet Supabase est en pause, réactive-le depuis son tableau de bord.")
        else:
            status.cause = cause
    _write(status, path)
    logger.info("Vérification de la base : %s", status.status)
    return status


def _try_send(status: DbStatus, send: Callable[[str, str], None], subject: str, body: str) -> None:
    try:
        send(subject, body)
        status.email_error = None
    except (MailNotConfigured, MailError) as error:
        status.email_error = str(error)
        logger.warning("Alerte non envoyée : %s", error)
    except Exception as error:  # noqa: BLE001 - l'échec de l'e-mail ne doit pas arrêter la surveillance
        status.email_error = f"envoi impossible ({type(error).__name__})"
        logger.exception("Alerte non envoyée")
