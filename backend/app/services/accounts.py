"""Création et recherche de comptes."""

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    Food,
    Inventory,
    InventoryItem,
    InventoryMember,
    Notification,
    PlannedMeal,
    Recipe,
    StorageLocation,
    User,
    UserPreferences,
)
from app.models.enums import InventoryKind, MemberRole, NotificationType, RecipeSource, StorageType, UserRole
from app.security import hash_password
from app.seed.utensils import give_default_utensils

DEFAULT_STORAGE_LOCATIONS = (
    ("Frigo", StorageType.FRIDGE),
    ("Congélateur", StorageType.FREEZER),
    ("Placard", StorageType.PANTRY),
    ("Épices", StorageType.SPICE_RACK),
    ("Corbeille à fruits", StorageType.FRUIT_BOWL),
)


class UsernameTaken(ValueError):
    pass


class SuperAdminCannotLeave(ValueError):
    pass


def _delete_inventory(session: Session, inventory_id) -> None:
    """Ordre imposé par les contraintes : repas mangeant un de ses restes, articles, puis l'inventaire."""
    items = select(InventoryItem.id).where(InventoryItem.inventory_id == inventory_id)
    session.execute(delete(PlannedMeal).where(PlannedMeal.leftover_item_id.in_(items)))
    session.execute(delete(InventoryItem).where(InventoryItem.inventory_id == inventory_id))
    session.execute(delete(Inventory).where(Inventory.id == inventory_id))


def delete_account(session: Session, user: User) -> None:
    """Supprime le compte et tout ce qui lui appartient.

    Inventaires partagés dont il est le seul administrateur : transmis au membre le plus
    ancien, ou supprimés s'il était seul. Ses aliments personnels encore utilisés dans un
    partage sont transmis à un membre de ce partage. N'effectue pas le commit.
    """
    if user.role == UserRole.SUPER_ADMIN:
        raise SuperAdminCannotLeave()

    memberships = session.scalars(select(InventoryMember).where(InventoryMember.user_id == user.id)).all()
    for membership in memberships:
        inventory = session.get(Inventory, membership.inventory_id)
        if inventory.kind != InventoryKind.SHARED:
            continue
        others = session.scalars(
            select(InventoryMember)
            .where(InventoryMember.inventory_id == inventory.id, InventoryMember.user_id != user.id)
            .order_by(InventoryMember.joined_at)
        ).all()
        if not others:
            _delete_inventory(session, inventory.id)
            continue
        if membership.role == MemberRole.ADMIN and not any(o.role == MemberRole.ADMIN for o in others):
            others[0].role = MemberRole.ADMIN
            session.add(Notification(user_id=others[0].user_id, type=NotificationType.SYSTEM, created_at=datetime.now(UTC),
                                     payload={"message": f"Tu es maintenant administrateur de « {inventory.name} »."}))
        # Ses aliments personnels encore présents dans ce partage passent à un autre membre.
        used_foods = select(InventoryItem.food_id).where(InventoryItem.inventory_id == inventory.id)
        for food in session.scalars(select(Food).where(Food.owner_user_id == user.id, Food.id.in_(used_foods))):
            food.owner_user_id = others[0].user_id
    session.flush()

    # Ses recettes personnelles (et les repas qui les utilisent, chez lui ou chez ceux qui les ont reçues).
    own_recipes = select(Recipe.id).where(Recipe.source == RecipeSource.USER, Recipe.author_user_id == user.id)
    session.execute(delete(PlannedMeal).where(PlannedMeal.recipe_id.in_(own_recipes)))
    session.execute(delete(Recipe).where(Recipe.id.in_(own_recipes)))

    personal = session.scalar(select(Inventory.id).where(Inventory.personal_owner_id == user.id))
    if personal:
        _delete_inventory(session, personal)
    session.execute(delete(User).where(User.id == user.id))
    session.flush()


def find_user_by_username(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(func.lower(User.username) == username.lower()))


def create_user(session: Session, username: str, display_name: str, password: str) -> User:
    """Crée le compte, ses préférences et son inventaire personnel avec les lieux standard.

    Ne valide pas la transaction : l'appelant fait le commit.
    """
    if find_user_by_username(session, username) is not None:
        raise UsernameTaken(username)

    user = User(username=username, display_name=display_name.strip(), password_hash=hash_password(password))
    session.add(user)
    session.flush()

    session.add(UserPreferences(user_id=user.id))

    inventory = Inventory(
        name="Mon inventaire", kind=InventoryKind.PERSONAL, created_by=user.id, personal_owner_id=user.id
    )
    session.add(inventory)
    session.flush()

    session.add(InventoryMember(inventory_id=inventory.id, user_id=user.id, role=MemberRole.ADMIN))
    for position, (name, storage_type) in enumerate(DEFAULT_STORAGE_LOCATIONS):
        session.add(
            StorageLocation(inventory_id=inventory.id, name=name, storage_type=storage_type, position=position)
        )
    give_default_utensils(session, user.id)
    session.flush()
    return user
