"""Purges nocturnes : historique au-delà d'un mois, analyses photo, sessions expirées…"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from app.models import (
    SignupInvitation,
    AuthSession,
    DailyAgentRun,
    DailyRecipe,
    InventoryItem,
    InventoryRemoval,
    Notification,
    PhotoScan,
    PlannedMeal,
    ShoppingListItem,
)
from app.models.enums import ScanStatus

logger = logging.getLogger("frigo.maintenance")

HISTORY_DAYS = 30
PHOTO_DAYS = 30
READ_NOTIFICATION_DAYS = 90


def purge(session: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    month_ago = now - timedelta(days=HISTORY_DAYS)
    counts = {}

    counts["retraits"] = session.execute(
        delete(InventoryRemoval).where(InventoryRemoval.removed_at < month_ago)
    ).rowcount

    # Articles archivés depuis plus d'un mois, sans historique restant ni repas qui les mentionne.
    counts["articles archivés"] = session.execute(
        delete(InventoryItem).where(
            InventoryItem.archived_at < month_ago,
            ~exists().where(InventoryRemoval.inventory_item_id == InventoryItem.id),
            ~exists().where(PlannedMeal.leftover_item_id == InventoryItem.id),
        )
    ).rowcount

    counts["analyses photo"] = session.execute(
        delete(PhotoScan).where(
            PhotoScan.created_at < now - timedelta(days=PHOTO_DAYS), PhotoScan.status != ScanStatus.ANALYZING
        )
    ).rowcount

    counts["sessions expirées"] = session.execute(delete(AuthSession).where(AuthSession.expires_at < now)).rowcount

    counts["liens d'inscription expirés"] = session.execute(
        delete(SignupInvitation).where(SignupInvitation.expires_at < now - timedelta(days=1))
    ).rowcount

    counts["recettes du jour"] = session.execute(
        delete(DailyRecipe).where(DailyRecipe.day < (now - timedelta(days=30)).date())
    ).rowcount
    counts["passages de l'agent"] = session.execute(
        delete(DailyAgentRun).where(DailyAgentRun.day < (now - timedelta(days=30)).date())
    ).rowcount

    counts["notifications lues"] = session.execute(
        delete(Notification).where(Notification.read_at < now - timedelta(days=READ_NOTIFICATION_DAYS))
    ).rowcount

    counts["achats manuels"] = session.execute(
        delete(ShoppingListItem).where(ShoppingListItem.purchased_at < month_ago)
    ).rowcount

    session.commit()
    logger.info("Purge : %s", counts)
    return counts
