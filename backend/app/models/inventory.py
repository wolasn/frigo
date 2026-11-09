"""Inventaires personnels et partagés, membres, lieux, articles et retraits."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, created_at_column, pg_enum, uuid_pk
from app.models.enums import (
    DateType,
    InventoryKind,
    InvitationStatus,
    ItemKind,
    ItemUnit,
    MemberRole,
    RemovalReason,
    StorageType,
)


class Inventory(TimestampMixin, Base):
    __tablename__ = "inventories"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[InventoryKind] = mapped_column(pg_enum(InventoryKind, "inventory_kind"), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Rempli seulement pour un inventaire personnel : supprimé avec son propriétaire,
    # et un seul inventaire personnel par utilisateur.
    personal_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )

    __table_args__ = (
        CheckConstraint(
            "(kind = 'personal') = (personal_owner_id IS NOT NULL)", name="personal_has_owner"
        ),
    )


class InventoryMember(Base):
    __tablename__ = "inventory_members"

    inventory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventories.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[MemberRole] = mapped_column(
        pg_enum(MemberRole, "member_role"), nullable=False, server_default=MemberRole.MEMBER.value
    )
    include_in_suggestions: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    joined_at: Mapped[datetime] = created_at_column()


class InventoryInvitation(Base):
    """Une invitation acceptée crée toujours un membre de rôle « member »."""

    __tablename__ = "inventory_invitations"

    id: Mapped[uuid.UUID] = uuid_pk()
    inventory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventories.id", ondelete="CASCADE"), nullable=False
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
            "uq_inventory_invitations_pending",
            "inventory_id", "invited_user_id",
            unique=True, postgresql_where=text("status = 'pending'"),
        ),
    )


class StorageLocation(Base):
    __tablename__ = "storage_locations"

    id: Mapped[uuid.UUID] = uuid_pk()
    inventory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventories.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    storage_type: Mapped[StorageType] = mapped_column(pg_enum(StorageType, "storage_type"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        UniqueConstraint("inventory_id", "name"),
        # Cible de la clé étrangère composée des articles : garantit qu'un article
        # est rangé dans un lieu de son propre inventaire.
        UniqueConstraint("inventory_id", "id"),
    )


class InventoryItem(TimestampMixin, Base):
    __tablename__ = "inventory_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    inventory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventories.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ItemKind] = mapped_column(pg_enum(ItemKind, "item_kind"), nullable=False)
    food_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="RESTRICT"), index=True
    )
    leftover_name: Mapped[str | None] = mapped_column(Text)
    source_recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="SET NULL")
    )
    # Unité de référence de l'aliment (g, ml, piece) ou nombre de parts pour un reste.
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit: Mapped[ItemUnit] = mapped_column(pg_enum(ItemUnit, "item_unit"), nullable=False)
    entered_unit: Mapped[str | None] = mapped_column(Text)  # unité saisie, pour l'affichage
    storage_location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entered_on: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    date_type: Mapped[DateType] = mapped_column(pg_enum(DateType, "date_type"), nullable=False)
    opened_on: Mapped[date | None] = mapped_column(Date)
    added_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["inventory_id", "storage_location_id"],
            ["storage_locations.inventory_id", "storage_locations.id"],
            ondelete="RESTRICT",
            name="fk_inventory_items_location_same_inventory",
        ),
        CheckConstraint("quantity >= 0", name="quantity_positive"),
        CheckConstraint(
            "(kind = 'ingredient' AND food_id IS NOT NULL AND unit <> 'portion')"
            " OR (kind = 'leftover' AND leftover_name IS NOT NULL AND unit = 'portion'"
            " AND date_type <> 'best_before')",
            name="kind_consistency",
        ),
        Index("ix_inventory_items_inventory_expires", "inventory_id", "expires_on"),
    )


class InventoryRemoval(Base):
    """Historique des retraits, consultable et restaurable pendant 1 mois."""

    __tablename__ = "inventory_removals"

    id: Mapped[uuid.UUID] = uuid_pk()
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    reason: Mapped[RemovalReason] = mapped_column(pg_enum(RemovalReason, "removal_reason"), nullable=False)
    planned_meal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("planned_meals.id", ondelete="SET NULL")
    )
    removed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    removed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)
