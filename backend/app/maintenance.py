"""Purges nocturnes : recettes que plus rien ne retient, achats d'il y a un mois, sessions expirées…"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import AuthSession, DailyRecipe, Notification, ShoppingListItem, SignupInvitation, WebSearchCache
from app.services.recipes import purge_unused_recipes

logger = logging.getLogger("frigo.maintenance")

HISTORY_DAYS = 30
SEARCH_CACHE_DAYS = 7
READ_NOTIFICATION_DAYS = 90


def purge(session: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    month_ago = now - timedelta(days=HISTORY_DAYS)
    counts = {}

    # Recettes web ou IA ni programmées, ni épinglées, ni en favori, ni partagées.
    counts["recettes"] = purge_unused_recipes(session)

    counts["recherches web"] = session.execute(
        delete(WebSearchCache).where(WebSearchCache.fetched_at < now - timedelta(days=SEARCH_CACHE_DAYS))
    ).rowcount

    counts["sessions expirées"] = session.execute(delete(AuthSession).where(AuthSession.expires_at < now)).rowcount

    counts["liens d'inscription expirés"] = session.execute(
        delete(SignupInvitation).where(SignupInvitation.expires_at < now - timedelta(days=1))
    ).rowcount

    counts["recettes du jour"] = session.execute(
        delete(DailyRecipe).where(DailyRecipe.day < (now - timedelta(days=30)).date())
    ).rowcount

    counts["notifications lues"] = session.execute(
        delete(Notification).where(Notification.read_at < now - timedelta(days=READ_NOTIFICATION_DAYS))
    ).rowcount

    counts["achats"] = session.execute(
        delete(ShoppingListItem).where(ShoppingListItem.purchased_at < month_ago)
    ).rowcount

    session.commit()
    logger.info("Purge : %s", counts)
    return counts
