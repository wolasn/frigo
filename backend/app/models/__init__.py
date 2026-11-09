"""Tous les modèles, importés ici pour qu'Alembic les voie dans Base.metadata."""

from app.models.accounts import AppSetting, AuthSession, User, UserCategoryThreshold, UserExcludedFood, UserPreferences
from app.models.base import Base
from app.models.catalog import Food, FoodAlias, FoodCategory, FoodShelfLife, UnitConversion, UserInfiniteFood
from app.models.inventory import (
    Inventory,
    InventoryInvitation,
    InventoryItem,
    InventoryMember,
    InventoryRemoval,
    StorageLocation,
)
from app.models.photo import PhotoScan, PhotoScanLine
from app.models.planning import Notification, PlannedMeal, Reservation, ShoppingListItem, ShoppingListItemMeal
from app.models.recipes import (
    MarmitonSearchCache,
    Recipe,
    RecipeIngredient,
    RecipeShare,
    RecipeStep,
    RecipeUtensil,
    Utensil,
    UserRecipeMeta,
    UserUtensil,
)

__all__ = [
    "AppSetting", "AuthSession", "Base", "Food", "FoodAlias", "FoodCategory", "FoodShelfLife", "Inventory",
    "InventoryInvitation", "InventoryItem", "InventoryMember", "InventoryRemoval", "MarmitonSearchCache",
    "Notification", "PhotoScan", "PhotoScanLine", "PlannedMeal", "Recipe", "RecipeIngredient", "RecipeShare",
    "RecipeStep", "RecipeUtensil", "Reservation", "ShoppingListItem", "ShoppingListItemMeal", "StorageLocation",
    "UnitConversion", "User", "UserCategoryThreshold", "UserExcludedFood", "UserInfiniteFood", "UserPreferences",
    "UserRecipeMeta", "UserUtensil", "Utensil",
]
