"""Tâches planifiées dans le processus de l'application (un seul processus uvicorn).

- 6 h 00 : vérification de la base (garde aussi le projet Supabase actif) ;
- 3 h 30 : purges (historique d'un mois, analyses photo, sessions expirées…) ;
- 4 h 00 : recettes du jour (trois par compte actif).
Les sauvegardes tournent dans le conteneur « backup » (pg_dump 17), pas ici.
"""

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.clock import APP_TIMEZONE

logger = logging.getLogger("frigo.scheduler")

_scheduler: BackgroundScheduler | None = None


def _check_database() -> None:
    from app.monitoring import run_check

    run_check()


def _purge() -> None:
    from app.db import get_engine
    from app.maintenance import purge

    try:
        with Session(get_engine()) as session:
            purge(session)
    except Exception:  # noqa: BLE001 - une purge ratée sera refaite la nuit suivante
        logger.exception("Purge impossible")


def _daily_recipes() -> None:
    from app.db import get_engine
    from app.services.daily import run_daily

    try:
        with Session(get_engine()) as session:
            logger.info("Recettes du jour préparées pour %s compte(s)", run_daily(session))
    except Exception:  # noqa: BLE001 - préparées à l'ouverture de l'onglet Repas à défaut
        logger.exception("Recettes du jour impossibles")


def start() -> None:
    global _scheduler
    if os.environ.get("SCHEDULER_ENABLED", "true").lower() != "true" or _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone=APP_TIMEZONE)
    # misfire_grace_time : si l'application était arrêtée à l'heure prévue, la tâche part au redémarrage (dans les 6 h).
    _scheduler.add_job(_check_database, CronTrigger(hour=6, minute=0, timezone=APP_TIMEZONE),
                       id="check_database", misfire_grace_time=6 * 3600, coalesce=True)
    _scheduler.add_job(_purge, CronTrigger(hour=3, minute=30, timezone=APP_TIMEZONE),
                       id="purge", misfire_grace_time=6 * 3600, coalesce=True)
    _scheduler.add_job(_daily_recipes, CronTrigger(hour=4, minute=0, timezone=APP_TIMEZONE),
                       id="daily_recipes", misfire_grace_time=6 * 3600, coalesce=True)
    _scheduler.start()
    logger.info("Tâches planifiées démarrées")


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
