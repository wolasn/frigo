"""Notifications dans l'application (invitations, retrait d'un partage, recettes partagées…)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import func, select, update

from app.api.deps import CurrentUser, DbSession
from app.models import InventoryInvitation, Notification
from app.models.enums import InvitationStatus, NotificationType

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: NotificationType
    message: str
    created_at: datetime
    read: bool


class Summary(BaseModel):
    unread: int
    pending_invitations: int
    items: list[NotificationOut]


def _message(kind: NotificationType, payload: dict[str, Any]) -> str:
    name = payload.get("inventory_name", "un inventaire")
    if kind == NotificationType.INVENTORY_INVITATION:
        return f"{payload.get('invited_by', 'Quelqu’un')} t'invite à rejoindre « {name} »."
    if kind == NotificationType.REMOVED_FROM_INVENTORY:
        if payload.get("reason") == "supprimé":
            return f"L'inventaire partagé « {name} » a été supprimé."
        return f"Tu as été retiré de l'inventaire partagé « {name} »."
    if kind == NotificationType.RECIPE_SHARED:
        return f"{payload.get('shared_by', 'Quelqu’un')} a partagé la recette « {payload.get('recipe_title', '')} »."
    return payload.get("message", "Notification")


@router.get("")
def list_notifications(session: DbSession, user: CurrentUser) -> Summary:
    rows = session.scalars(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(30)
    ).all()
    # Une invitation en attente est déjà comptée dans pending_invitations : pas deux fois.
    unread = session.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
            Notification.type != NotificationType.INVENTORY_INVITATION,
        )
    )
    pending = session.scalar(
        select(func.count()).select_from(InventoryInvitation).where(
            InventoryInvitation.invited_user_id == user.id, InventoryInvitation.status == InvitationStatus.PENDING
        )
    )
    return Summary(
        unread=unread,
        pending_invitations=pending,
        items=[NotificationOut(id=n.id, type=n.type, message=_message(n.type, n.payload or {}), created_at=n.created_at,
                               read=n.read_at is not None) for n in rows],
    )


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(session: DbSession, user: CurrentUser) -> None:
    session.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    session.commit()
