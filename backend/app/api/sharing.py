"""Agendas partagés : création, membres, rôles, invitations, départ.

Chaque agenda partagé a sa liste de courses. Droits : tout membre voit l'agenda, coche les achats et
ajoute des lignes à la liste ; le contributeur programme, déplace et retire des repas ; l'administrateur
gère en plus les membres, leurs rôles, renomme et supprime l'agenda. Il reste toujours au moins un administrateur.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.models import AgendaInvitation, AgendaMember, Notification, SharedAgenda, User
from app.models.enums import InvitationStatus, MemberRole, NotificationType
from app.services.accounts import find_user_by_username
from app.services.recipes import purge_unused_recipes

router = APIRouter(prefix="/api", tags=["partages"])


# ---------- Schémas ----------


class AgendaName(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class AgendaOut(BaseModel):
    id: uuid.UUID
    name: str
    my_role: MemberRole


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


class AgendaDetail(AgendaOut):
    members: list[MemberOut]
    invitations: list[PendingInvitation]


class InviteIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class RoleIn(BaseModel):
    role: MemberRole


class MyInvitation(BaseModel):
    id: uuid.UUID
    agenda_id: uuid.UUID
    agenda_name: str
    invited_by: str | None
    created_at: datetime


# ---------- Outils ----------


def membership(session: Session, user: User, agenda_id: uuid.UUID) -> tuple[SharedAgenda, AgendaMember]:
    agenda = session.get(SharedAgenda, agenda_id)
    member = session.get(AgendaMember, (agenda_id, user.id)) if agenda else None
    if agenda is None or member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agenda introuvable.")
    return agenda, member


def _require_admin(session: Session, user: User, agenda_id: uuid.UUID) -> SharedAgenda:
    agenda, member = membership(session, user, agenda_id)
    if member.role != MemberRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Réservé aux administrateurs de cet agenda.")
    return agenda


def _admin_count(session: Session, agenda_id: uuid.UUID) -> int:
    return session.scalar(select(func.count()).select_from(AgendaMember).where(
        AgendaMember.agenda_id == agenda_id, AgendaMember.role == MemberRole.ADMIN))


def _notify(session: Session, user_id: uuid.UUID, kind: NotificationType, **payload) -> None:
    session.add(Notification(user_id=user_id, type=kind, payload={k: str(v) for k, v in payload.items()},
                             created_at=datetime.now(UTC)))  # heure exacte, pas celle du début de transaction


def _detail(session: Session, user: User, agenda: SharedAgenda) -> AgendaDetail:
    me = session.get(AgendaMember, (agenda.id, user.id))
    members = session.execute(
        select(AgendaMember, User).join(User, User.id == AgendaMember.user_id)
        .where(AgendaMember.agenda_id == agenda.id).order_by(AgendaMember.role, User.display_name)
    ).all()
    invitations = session.execute(
        select(AgendaInvitation, User).join(User, User.id == AgendaInvitation.invited_user_id)
        .where(AgendaInvitation.agenda_id == agenda.id, AgendaInvitation.status == InvitationStatus.PENDING)
    ).all()
    return AgendaDetail(
        id=agenda.id, name=agenda.name, my_role=me.role,
        members=[MemberOut(user_id=u.id, username=u.username, display_name=u.display_name, role=m.role,
                           is_me=u.id == user.id) for m, u in members],
        invitations=[PendingInvitation(id=i.id, username=u.username, display_name=u.display_name) for i, u in invitations],
    )


# ---------- Agendas ----------


@router.get("/agendas")
def list_agendas(session: DbSession, user: CurrentUser) -> list[AgendaOut]:
    rows = session.execute(
        select(SharedAgenda, AgendaMember.role).join(AgendaMember, AgendaMember.agenda_id == SharedAgenda.id)
        .where(AgendaMember.user_id == user.id).order_by(SharedAgenda.name)
    ).all()
    return [AgendaOut(id=a.id, name=a.name, my_role=role) for a, role in rows]


@router.post("/agendas", status_code=status.HTTP_201_CREATED)
def create_agenda(body: AgendaName, session: DbSession, user: CurrentUser) -> AgendaDetail:
    agenda = SharedAgenda(name=body.name.strip(), created_by=user.id)
    session.add(agenda)
    session.flush()
    session.add(AgendaMember(agenda_id=agenda.id, user_id=user.id, role=MemberRole.ADMIN))
    session.commit()
    return _detail(session, user, agenda)


@router.get("/agendas/{agenda_id}")
def agenda_detail(agenda_id: uuid.UUID, session: DbSession, user: CurrentUser) -> AgendaDetail:
    agenda, _ = membership(session, user, agenda_id)
    return _detail(session, user, agenda)


@router.patch("/agendas/{agenda_id}")
def rename_agenda(agenda_id: uuid.UUID, body: AgendaName, session: DbSession, user: CurrentUser) -> AgendaDetail:
    agenda = _require_admin(session, user, agenda_id)
    agenda.name = body.name.strip()
    session.commit()
    return _detail(session, user, agenda)


@router.delete("/agendas/{agenda_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agenda(agenda_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    """Supprime l'agenda partagé : ses repas et sa liste de courses disparaissent."""
    agenda = _require_admin(session, user, agenda_id)
    for member in session.scalars(select(AgendaMember).where(AgendaMember.agenda_id == agenda.id)):
        if member.user_id != user.id:
            _notify(session, member.user_id, NotificationType.REMOVED_FROM_AGENDA, agenda_name=agenda.name, reason="supprimé")
    session.delete(agenda)
    session.flush()
    purge_unused_recipes(session)
    session.commit()


# ---------- Membres ----------


@router.patch("/agendas/{agenda_id}/members/{user_id}")
def change_role(agenda_id: uuid.UUID, user_id: uuid.UUID, body: RoleIn, session: DbSession, user: CurrentUser) -> AgendaDetail:
    agenda = _require_admin(session, user, agenda_id)
    member = session.get(AgendaMember, (agenda_id, user_id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Membre introuvable.")
    if member.role == MemberRole.ADMIN and body.role != MemberRole.ADMIN and _admin_count(session, agenda_id) == 1:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Il faut au moins un administrateur : nommes-en un autre d'abord.")
    member.role = body.role
    session.commit()
    return _detail(session, user, agenda)


@router.delete("/agendas/{agenda_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(agenda_id: uuid.UUID, user_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    """Un membre peut partir ; un administrateur peut retirer n'importe quel membre."""
    agenda, me = membership(session, user, agenda_id)
    leaving_self = user_id == user.id
    if not leaving_self and me.role != MemberRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Réservé aux administrateurs de cet agenda.")
    member = session.get(AgendaMember, (agenda_id, user_id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Membre introuvable.")
    if member.role == MemberRole.ADMIN and _admin_count(session, agenda_id) == 1:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Tu es le dernier administrateur : nomme un autre administrateur ou supprime l'agenda.")
    session.delete(member)
    if not leaving_self:
        _notify(session, user_id, NotificationType.REMOVED_FROM_AGENDA, agenda_name=agenda.name, reason="retiré")
    session.commit()


# ---------- Invitations ----------


@router.post("/agendas/{agenda_id}/invitations", status_code=status.HTTP_201_CREATED)
def invite(agenda_id: uuid.UUID, body: InviteIn, session: DbSession, user: CurrentUser) -> AgendaDetail:
    agenda = _require_admin(session, user, agenda_id)
    invited = find_user_by_username(session, body.username.strip())
    if invited is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Aucun compte avec l'identifiant « {body.username.strip()} ».")
    if session.get(AgendaMember, (agenda_id, invited.id)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{invited.display_name} fait déjà partie de l'agenda.")
    pending = session.scalar(select(AgendaInvitation.id).where(
        AgendaInvitation.agenda_id == agenda_id, AgendaInvitation.invited_user_id == invited.id,
        AgendaInvitation.status == InvitationStatus.PENDING))
    if pending:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{invited.display_name} a déjà une invitation en attente.")
    session.add(AgendaInvitation(agenda_id=agenda_id, invited_user_id=invited.id, invited_by=user.id))
    _notify(session, invited.id, NotificationType.AGENDA_INVITATION, agenda_name=agenda.name, invited_by=user.display_name)
    session.commit()
    return _detail(session, user, agenda)


@router.delete("/agendas/{agenda_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_invitation(agenda_id: uuid.UUID, invitation_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    _require_admin(session, user, agenda_id)
    invitation = session.get(AgendaInvitation, invitation_id)
    if invitation is None or invitation.agenda_id != agenda_id or invitation.status != InvitationStatus.PENDING:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invitation introuvable.")
    invitation.status, invitation.answered_at = InvitationStatus.CANCELLED, datetime.now(UTC)
    session.commit()


@router.get("/invitations")
def my_invitations(session: DbSession, user: CurrentUser) -> list[MyInvitation]:
    rows = session.execute(
        select(AgendaInvitation, SharedAgenda.name, User.display_name)
        .join(SharedAgenda, SharedAgenda.id == AgendaInvitation.agenda_id)
        .outerjoin(User, User.id == AgendaInvitation.invited_by)
        .where(AgendaInvitation.invited_user_id == user.id, AgendaInvitation.status == InvitationStatus.PENDING)
        .order_by(AgendaInvitation.created_at.desc())
    ).all()
    return [MyInvitation(id=i.id, agenda_id=i.agenda_id, agenda_name=name, invited_by=by, created_at=i.created_at)
            for i, name, by in rows]


def _my_pending_invitation(session: Session, user: User, invitation_id: uuid.UUID) -> AgendaInvitation:
    invitation = session.get(AgendaInvitation, invitation_id)
    if invitation is None or invitation.invited_user_id != user.id or invitation.status != InvitationStatus.PENDING:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invitation introuvable.")
    return invitation


@router.post("/invitations/{invitation_id}/accept")
def accept_invitation(invitation_id: uuid.UUID, session: DbSession, user: CurrentUser) -> AgendaDetail:
    invitation = _my_pending_invitation(session, user, invitation_id)
    invitation.status, invitation.answered_at = InvitationStatus.ACCEPTED, datetime.now(UTC)
    if session.get(AgendaMember, (invitation.agenda_id, user.id)) is None:
        session.add(AgendaMember(agenda_id=invitation.agenda_id, user_id=user.id, role=MemberRole.MEMBER))
    session.commit()
    return _detail(session, user, session.get(SharedAgenda, invitation.agenda_id))


@router.post("/invitations/{invitation_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
def decline_invitation(invitation_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    invitation = _my_pending_invitation(session, user, invitation_id)
    invitation.status, invitation.answered_at = InvitationStatus.DECLINED, datetime.now(UTC)
    session.commit()
