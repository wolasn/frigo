"""Création et recherche de comptes."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Inventory, InventoryMember, StorageLocation, User, UserPreferences
from app.models.enums import InventoryKind, MemberRole, StorageType
from app.security import hash_password

DEFAULT_STORAGE_LOCATIONS = (
    ("Frigo", StorageType.FRIDGE),
    ("Congélateur", StorageType.FREEZER),
    ("Placard", StorageType.PANTRY),
    ("Épices", StorageType.SPICE_RACK),
    ("Corbeille à fruits", StorageType.FRUIT_BOWL),
)


class UsernameTaken(ValueError):
    pass


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
    session.flush()
    return user
