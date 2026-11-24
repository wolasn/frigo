"""Agendas partagés : membres (avec un rôle) et invitations. L'agenda personnel n'a pas de ligne ici."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, created_at_column, pg_enum, uuid_pk
from app.models.enums import InvitationStatus, MemberRole


class SharedAgenda(TimestampMixin, Base):
    __tablename__ = "shared_agendas"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class AgendaMember(Base):
    __tablename__ = "agenda_members"

    agenda_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shared_agendas.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[MemberRole] = mapped_column(
        pg_enum(MemberRole, "member_role"), nullable=False, server_default=MemberRole.MEMBER.value
    )
    joined_at: Mapped[datetime] = created_at_column()


class AgendaInvitation(Base):
    """Une invitation acceptée crée toujours un membre de rôle « member »."""

    __tablename__ = "agenda_invitations"

    id: Mapped[uuid.UUID] = uuid_pk()
    agenda_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shared_agendas.id", ondelete="CASCADE"), nullable=False
    )
    invited_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[InvitationStatus] = mapped_column(
        pg_enum(InvitationStatus, "invitation_status"),
        nullable=False,
        server_default=InvitationStatus.PENDING.value,
    )
    created_at: Mapped[datetime] = created_at_column()
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_agenda_invitations_pending",
            "agenda_id", "invited_user_id",
            unique=True, postgresql_where=text("status = 'pending'"),
        ),
    )
