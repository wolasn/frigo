"""Agenda (personnel et partagé), réservations, liste de courses et notifications."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, created_at_column, pg_enum, uuid_pk
from app.models.enums import MealSlot, MealStatus, NotificationType, ShoppingOrigin


class PlannedMeal(TimestampMixin, Base):
    """Un créneau peut porter autant de repas que voulu : aucune unicité sur (date, créneau)."""

    __tablename__ = "planned_meals"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Vide = agenda personnel ; rempli = agenda partagé de cet inventaire.
    shared_inventory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventories.id", ondelete="CASCADE")
    )
    meal_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot: Mapped[MealSlot] = mapped_column(pg_enum(MealSlot, "meal_slot"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="RESTRICT"), index=True
    )
    leftover_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True
    )
    servings: Mapped[int] = mapped_column(Integer, nullable=False)  # personnes, ou parts pour un reste
    status: Mapped[MealStatus] = mapped_column(
        pg_enum(MealStatus, "meal_status"), nullable=False, server_default=MealStatus.PLANNED.value
    )
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("(recipe_id IS NULL) <> (leftover_item_id IS NULL)", name="recipe_xor_leftover"),
        CheckConstraint("servings BETWEEN 1 AND 999", name="servings_range"),
        Index("ix_planned_meals_user_date", "user_id", "meal_date"),
        Index("ix_planned_meals_shared_date", "shared_inventory_id", "meal_date"),
    )


class Reservation(Base):
    """Donnée dérivée : reconstruite par le moteur de calcul."""

    __tablename__ = "reservations"

    id: Mapped[uuid.UUID] = uuid_pk()
    planned_meal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("planned_meals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    computed_at: Mapped[datetime] = created_at_column()

    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)


class ShoppingListItem(Base):
    __tablename__ = "shopping_list_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Vide = liste personnelle ; rempli = liste partagée de cet inventaire.
    shared_inventory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventories.id", ondelete="CASCADE"), index=True
    )
    origin: Mapped[ShoppingOrigin] = mapped_column(pg_enum(ShoppingOrigin, "shopping_origin"), nullable=False)
    food_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("foods.id", ondelete="SET NULL"))
    label: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(Text)
    recommended_purchase_on: Mapped[date | None] = mapped_column(Date)  # vide = dès que possible
    is_perishable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    expiry_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purchased_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_column()


class ShoppingListItemMeal(Base):
    """Donnée dérivée : part du manque due à chaque repas planifié."""

    __tablename__ = "shopping_list_item_meals"

    shopping_list_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shopping_list_items.id", ondelete="CASCADE"), primary_key=True
    )
    planned_meal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("planned_meals.id", ondelete="CASCADE"), primary_key=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)


class Notification(Base):
    """Les alertes de péremption ne sont pas stockées : elles sont calculées à l'affichage."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[NotificationType] = mapped_column(pg_enum(NotificationType, "notification_type"), nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = created_at_column()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)
