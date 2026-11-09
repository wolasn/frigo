"""Date du jour dans le fuseau de l'application (Europe/Paris par défaut), et non en UTC."""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

APP_TIMEZONE = ZoneInfo(os.environ.get("APP_TIMEZONE", "Europe/Paris"))


def today() -> date:
    return datetime.now(APP_TIMEZONE).date()
