from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Ingredient(Base):
    __tablename__ = "ingredients"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    category: Mapped[str]
    unit: Mapped[str]
    restriction: Mapped[str | None]


class Package(Base):
    __tablename__ = "packages"
    ingredient_id: Mapped[str] = mapped_column(ForeignKey("ingredients.id"), primary_key=True)
    quantity: Mapped[int]


class IngredientPrice(Base):
    __tablename__ = "ingredient_prices"
    ingredient_id: Mapped[str] = mapped_column(ForeignKey("packages.ingredient_id"), primary_key=True)
    price_pkr: Mapped[int]


class Recipe(Base):
    __tablename__ = "recipes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    category: Mapped[str]
    servings: Mapped[int]
    minutes: Mapped[int]
    instructions: Mapped[list[str]] = mapped_column(JSON)
    traditional: Mapped[bool]
    protein_rich_ingredients: Mapped[bool]


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), primary_key=True)
    ingredient_id: Mapped[str] = mapped_column(ForeignKey("ingredients.id"), primary_key=True)
    quantity: Mapped[int]


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    request: Mapped[dict] = mapped_column(JSON)
    snapshot: Mapped[dict] = mapped_column(JSON)


class PlannedMeal(Base):
    __tablename__ = "planned_meals"
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"))
    batch: Mapped[dict] = mapped_column(JSON)
