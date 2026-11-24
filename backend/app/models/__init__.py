"""Tous les modèles, importés ici pour qu'Alembic les voie dans Base.metadata."""

from app.models.accounts import (
    AiUsage,
    AppSetting,
    AuthSession,
    SignupInvitation,
    User,
    UserExcludedFood,
    UserPreferences,
)
from app.models.base import Base
from app.models.catalog import Food, FoodAlias, FoodCategory, FoodShelfLife, UnitConversion
from app.models.planning import DailyRecipe, Notification, PlannedMeal, ShoppingListItem, ShoppingListItemMeal
from app.models.recipes import (
    IngredientTerm,
    Recipe,
    RecipeIngredient,
    RecipeShare,
    RecipeStep,
    RecipeUtensil,
    Utensil,
    UserRecipeMeta,
    UserUtensil,
    WebSearchCache,
)
from app.models.sharing import AgendaInvitation, AgendaMember, SharedAgenda

__all__ = [
    "AgendaInvitation",
    "AgendaMember",
    "AiUsage",
    "AppSetting",
    "AuthSession",
    "Base",
    "DailyRecipe",
    "Food",
    "FoodAlias",
    "FoodCategory",
    "FoodShelfLife",
    "IngredientTerm",
    "Notification",
    "PlannedMeal",
    "Recipe",
    "RecipeIngredient",
    "RecipeShare",
    "RecipeStep",
    "RecipeUtensil",
    "SharedAgenda",
    "ShoppingListItem",
    "ShoppingListItemMeal",
    "SignupInvitation",
    "UnitConversion",
    "User",
    "UserExcludedFood",
    "UserPreferences",
    "UserRecipeMeta",
    "UserUtensil",
    "Utensil",
    "WebSearchCache",
]
