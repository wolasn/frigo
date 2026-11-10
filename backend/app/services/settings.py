"""Paramètres globaux réglés par le super-administrateur (table app_settings). Jamais de secret ici."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AppSetting
from app.services.ai_recipes import MODEL as DEFAULT_RECIPE_MODEL
from app.services.photo import DEFAULT_LOCAL_MODEL, DEFAULT_OLLAMA_URL

DEFAULTS: dict[str, Any] = {
    "photo_engine": "claude",  # claude | local
    "photo_local_url": DEFAULT_OLLAMA_URL,
    "photo_local_model": DEFAULT_LOCAL_MODEL,
    "ai_recipe_model": DEFAULT_RECIPE_MODEL,  # claude-opus-5-5 | claude-sonnet-5-5 | claude-haiku-5-5
}


def get_setting(session: Session, key: str) -> Any:
    row = session.get(AppSetting, key)
    return row.value if row is not None else DEFAULTS[key]


def set_setting(session: Session, key: str, value: Any, user_id: uuid.UUID) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value, updated_by=user_id))
    else:
        row.value, row.updated_by = value, user_id
