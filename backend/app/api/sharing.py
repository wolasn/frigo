"""Inventaires partagés : création, membres, rôles, invitations, départ, lieux de rangement.

Droits : tout membre voit, ajoute, modifie et retire des aliments ; l'administrateur gère
les membres, leurs rôles, les lieux et peut supprimer l'inventaire. Un inventaire partagé
garde toujours au moins un administrateur.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.models import (
    Inventory,
    InventoryInvitation,
    InventoryItem,
    InventoryMember,
    Notification,
    PlannedMeal,
    StorageLocation,
    User,
)
from app.models.enums import InventoryKind, InvitationStatus, MemberRole, NotificationType
from app.services.accounts import DEFAULT_STORAGE_LOCATIONS, find_user_by_username
from app.services.planning import recompute_reservations

router = APIRouter(prefix="/api", tags=["partages"])


# ---------- Schémas ----------


class InventoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class InventoryRename(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class MemberOut(BaseModel):
    user_id: uuid.UUID
    username: str
    display_name: str
    role: MemberRole
    is_me: bool


class PendingInvitation(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str


class InventoryDetail(BaseModel):
    id: uuid.UUID
    name: str
    kind: InventoryKind
    my_role: MemberRole
    include_in_suggestions: bool
    members: list[MemberOut]
    invitations: list[PendingInvitation]


class InviteIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class RoleIn(BaseModel):
    role: MemberRole


class MyMembershipIn(BaseModel):
    include_in_suggestions: bool


class MyInvitation(BaseModel):
    id: uuid.UUID
    inventory_id: uuid.UUID
    inventory_name: str
    invited_by: str | None
    created_at: datetime


# ---------- Outils ----------


def _membership(session: Session, user: User, inventory_id: uuid.UUID) -> tuple[Inventory, InventoryMember]:
    inventory = session.get(Inventory, inventory_id)
    member = session.get(InventoryMember, (inventory_id, user.id)) if inventory else None
    if inventory is None or member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Inventaire introuvable.")
    return inventory, member


def _require_admin(session: Session, user: User, inventory_id: uuid.UUID) -> Inventory:
    inventory, member = _membership(session, user, inventory_id)
    if member.role != MemberRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Réservé aux administrateurs de cet inventaire.")
    return inventory


def _require_shared(inventory: Inventory) -> None:
    if inventory.kind != InventoryKind.SHARED:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ton inventaire personnel ne se partage pas.")


def _admin_count(session: Session, inventory_id: uuid.UUID) -> int:
    return session.scalar(
        select(func.count()).select_from(InventoryMember).where(
            InventoryMember.inventory_id == inventory_id, InventoryMember.role == MemberRole.ADMIN
        )
    )


def _notify(session: Session, user_id: uuid.UUID, kind: NotificationType, **payload) -> None:
    session.add(Notification(user_id=user_id, type=kind, payload={k: str(v) for k, v in payload.items()},
                             created_at=datetime.now(UTC)))  # heure exacte, pas celle du début de transaction


def _detail(session: Session, user: User, inventory: Inventory) -> InventoryDetail:
    me = session.get(InventoryMember, (inventory.id, user.id))
    members = session.execute(
        select(InventoryMember, User)
        .join(User, User.id == InventoryMember.user_id)
        .where(InventoryMember.inventory_id == inventory.id)
        .order_by(InventoryMember.role, User.display_name)
    ).all()
    invitations = session.execute(
        select(InventoryInvitation, User)
        .join(User, User.id == InventoryInvitation.invited_user_id)
        .where(InventoryInvitation.inventory_id == inventory.id, InventoryInvitation.status == InvitationStatus.PENDING)
    ).all()
    return InventoryDetail(
        id=inventory.id, name=inventory.name, kind=inventory.kind, my_role=me.role,
        include_in_suggestions=me.include_in_suggestions,
        members=[MemberOut(user_id=u.id, username=u.username, display_name=u.display_name, role=m.role,
                           is_me=u.id == user.id) for m, u in members],
        invitations=[PendingInvitation(id=i.id, username=u.username, display_name=u.display_name)
                     for i, u in invitations],
    )


# ---------- Inventaires ----------


@router.post("/inventories", status_code=status.HTTP_201_CREATED)
def create_shared_inventory(body: InventoryCreate, session: DbSession, user: CurrentUser) -> InventoryDetail:
    inventory = Inventory(name=body.name.strip(), kind=InventoryKind.SHARED, created_by=user.id)
    session.add(inventory)
    session.flush()
    session.add(InventoryMember(inventory_id=inventory.id, user_id=user.id, role=MemberRole.ADMIN))
    for position, (name, storage_type) in enumerate(DEFAULT_STORAGE_LOCATIONS):
        session.add(StorageLocation(inventory_id=inventory.id, name=name, storage_type=storage_type, position=position))
    session.commit()
    return _detail(session, user, inventory)


@router.get("/inventories/{inventory_id}")
def inventory_detail(inventory_id: uuid.UUID, session: DbSession, user: CurrentUser) -> InventoryDetail:
    inventory, _ = _membership(session, user, inventory_id)
    return _detail(session, user, inventory)


@router.patch("/inventories/{inventory_id}")
def rename_inventory(inventory_id: uuid.UUID, body: InventoryRename, session: DbSession, user: CurrentUser) -> InventoryDetail:
    inventory, member = _membership(session, user, inventory_id)
    if inventory.kind == InventoryKind.SHARED and member.role != MemberRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Réservé aux administrateurs de cet inventaire.")
    inventory.name = body.name.strip()
    session.commit()
    return _detail(session, user, inventory)


@router.delete("/inventories/{inventory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inventory(inventory_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    """Supprime le partage : ses aliments, son agenda et sa liste de courses disparaissent."""
    inventory = _require_admin(session, user, inventory_id)
    _require_shared(inventory)
    for member in session.scalars(select(InventoryMember).where(InventoryMember.inventory_id == inventory.id)):
        if member.user_id != user.id:
            _notify(session, member.user_id, NotificationType.REMOVED_FROM_INVENTORY,
                    inventory_name=inventory.name, reason="supprimé")
    # Ordre imposé par les contraintes : repas qui mangent un reste de l'inventaire, puis ses
    # articles (avec leur historique et leurs réservations), puis l'inventaire et le reste en cascade.
    item_ids = select(InventoryItem.id).where(InventoryItem.inventory_id == inventory.id)
    session.execute(delete(PlannedMeal).where(PlannedMeal.leftover_item_id.in_(item_ids)))
    session.execute(delete(InventoryItem).where(InventoryItem.inventory_id == inventory.id))
    session.execute(delete(Inventory).where(Inventory.id == inventory.id))
    session.flush()
    recompute_reservations(session)
    session.commit()


@router.put("/inventories/{inventory_id}/me")
def update_my_membership(inventory_id: uuid.UUID, body: MyMembershipIn, session: DbSession, user: CurrentUser) -> InventoryDetail:
    inventory, member = _membership(session, user, inventory_id)
    member.include_in_suggestions = body.include_in_suggestions
    session.flush()
    recompute_reservations(session)
    session.commit()
    return _detail(session, user, inventory)


# ---------- Membres ----------


@router.patch("/inventories/{inventory_id}/members/{user_id}")
def change_role(inventory_id: uuid.UUID, user_id: uuid.UUID, body: RoleIn, session: DbSession, user: CurrentUser) -> InventoryDetail:
    inventory = _require_admin(session, user, inventory_id)
    _require_shared(inventory)
    member = session.get(InventoryMember, (inventory_id, user_id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Membre introuvable.")
    if member.role == MemberRole.ADMIN and body.role != MemberRole.ADMIN and _admin_count(session, inventory_id) == 1:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Il faut au moins un administrateur : nommes-en un autre d'abord.")
    member.role = body.role
    session.commit()
    return _detail(session, user, inventory)


@router.delete("/inventories/{inventory_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(inventory_id: uuid.UUID, user_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    """Un membre peut partir ; un administrateur peut retirer n'importe quel membre."""
    inventory, me = _membership(session, user, inventory_id)
    _require_shared(inventory)
    leaving_self = user_id == user.id
    if not leaving_self and me.role != MemberRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Réservé aux administrateurs de cet inventaire.")
    member = session.get(InventoryMember, (inventory_id, user_id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Membre introuvable.")
    if member.role == MemberRole.ADMIN and _admin_count(session, inventory_id) == 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Tu es le dernier administrateur : nomme un autre administrateur ou supprime l'inventaire.",
        )
    session.delete(member)
    if not leaving_self:
        _notify(session, user_id, NotificationType.REMOVED_FROM_INVENTORY, inventory_name=inventory.name, reason="retiré")
    session.flush()
    recompute_reservations(session)
    session.commit()


# ---------- Invitations ----------


@router.post("/inventories/{inventory_id}/invitations", status_code=status.HTTP_201_CREATED)
def invite(inventory_id: uuid.UUID, body: InviteIn, session: DbSession, user: CurrentUser) -> InventoryDetail:
    inventory = _require_admin(session, user, inventory_id)
    _require_shared(inventory)
    invited = find_user_by_username(session, body.username.strip())
    if invited is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Aucun compte avec l'identifiant « {body.username.strip()} ».")
    if session.get(InventoryMember, (inventory_id, invited.id)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{invited.display_name} fait déjà partie de l'inventaire.")
    pending = session.scalar(
        select(InventoryInvitation.id).where(
            InventoryInvitation.inventory_id == inventory_id, InventoryInvitation.invited_user_id == invited.id,
            InventoryInvitation.status == InvitationStatus.PENDING,
        )
    )
    if pending:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{invited.display_name} a déjà une invitation en attente.")
    session.add(InventoryInvitation(inventory_id=inventory_id, invited_user_id=invited.id, invited_by=user.id))
    _notify(session, invited.id, NotificationType.INVENTORY_INVITATION, inventory_name=inventory.name,
            invited_by=user.display_name)
    session.commit()
    return _detail(session, user, inventory)


@router.delete("/inventories/{inventory_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_invitation(inventory_id: uuid.UUID, invitation_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    _require_admin(session, user, inventory_id)
    invitation = session.get(InventoryInvitation, invitation_id)
    if invitation is None or invitation.inventory_id != inventory_id or invitation.status != InvitationStatus.PENDING:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invitation introuvable.")
    invitation.status, invitation.answered_at = InvitationStatus.CANCELLED, datetime.now(UTC)
    session.commit()


@router.get("/invitations")
def my_invitations(session: DbSession, user: CurrentUser) -> list[MyInvitation]:
    rows = session.execute(
        select(InventoryInvitation, Inventory.name, User.display_name)
        .join(Inventory, Inventory.id == InventoryInvitation.inventory_id)
        .outerjoin(User, User.id == InventoryInvitation.invited_by)
        .where(InventoryInvitation.invited_user_id == user.id, InventoryInvitation.status == InvitationStatus.PENDING)
        .order_by(InventoryInvitation.created_at.desc())
    ).all()
    return [MyInvitation(id=i.id, inventory_id=i.inventory_id, inventory_name=name, invited_by=by, created_at=i.created_at)
            for i, name, by in rows]


def _my_pending_invitation(session: Session, user: User, invitation_id: uuid.UUID) -> InventoryInvitation:
    invitation = session.get(InventoryInvitation, invitation_id)
    if invitation is None or invitation.invited_user_id != user.id or invitation.status != InvitationStatus.PENDING:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invitation introuvable.")
    return invitation


@router.post("/invitations/{invitation_id}/accept")
def accept_invitation(invitation_id: uuid.UUID, session: DbSession, user: CurrentUser) -> InventoryDetail:
    invitation = _my_pending_invitation(session, user, invitation_id)
    invitation.status, invitation.answered_at = InvitationStatus.ACCEPTED, datetime.now(UTC)
    if session.get(InventoryMember, (invitation.inventory_id, user.id)) is None:
        session.add(InventoryMember(inventory_id=invitation.inventory_id, user_id=user.id, role=MemberRole.MEMBER))
    session.flush()
    recompute_reservations(session)
    session.commit()
    return _detail(session, user, session.get(Inventory, invitation.inventory_id))


@router.post("/invitations/{invitation_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
def decline_invitation(invitation_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    invitation = _my_pending_invitation(session, user, invitation_id)
    invitation.status, invitation.answered_at = InvitationStatus.DECLINED, datetime.now(UTC)
    session.commit()
