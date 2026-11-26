from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Ingredient, IngredientPrice, Package, Recipe, RecipeIngredient
from .schemas import Amount, IngredientInfo, RecipeInfo


def ingredients(db: Session) -> dict[str, IngredientInfo]:
    statement = (
        select(Ingredient, Package, IngredientPrice)
        .select_from(Ingredient)
        .join(Package, Package.ingredient_id == Ingredient.id)
        .join(IngredientPrice, IngredientPrice.ingredient_id == Package.ingredient_id)
        .order_by(Ingredient.id)
    )
    rows = db.execute(statement)
    return {
        item.id: IngredientInfo(id=item.id, name=item.name, category=item.category, unit=item.unit,
                                restriction=item.restriction, package_quantity=package.quantity,
                                package_price_pkr=price.price_pkr)
        for item, package, price in rows
    }


def recipes(db: Session, catalog: dict[str, IngredientInfo]) -> list[RecipeInfo]:
    amounts = defaultdict(list)
    for line in db.scalars(select(RecipeIngredient).order_by(RecipeIngredient.ingredient_id)):
        item = catalog[line.ingredient_id]
        amounts[line.recipe_id].append(Amount(id=item.id, name=item.name, unit=item.unit, quantity=line.quantity))
    return [
        RecipeInfo(id=recipe.id, name=recipe.name, category=recipe.category, servings=recipe.servings,
                   minutes=recipe.minutes, instructions=recipe.instructions, ingredients=amounts[recipe.id],
                   dietary_flags=sorted({catalog[line.id].restriction for line in amounts[recipe.id]} - {None}),
                   traditional=recipe.traditional, protein_rich_ingredients=recipe.protein_rich_ingredients)
        for recipe in db.scalars(select(Recipe).order_by(Recipe.id))
    ]
