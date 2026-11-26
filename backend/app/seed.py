import csv
import json
from pathlib import Path

from sqlalchemy.orm import Session

from .db import engine
from .models import Ingredient, IngredientPrice, Package, Recipe, RecipeIngredient

DATA = Path(__file__).resolve().parents[2] / "data"


def load_seed(db: Session):
    with (DATA / "ingredients.tsv").open() as source:
        for row in csv.DictReader(source, delimiter="\t"):
            key = row["id"]
            db.merge(Ingredient(id=key, name=row["name"], category=row["category"],
                                unit=row["unit"], restriction=row["restriction"] or None))
            db.flush()
            db.merge(Package(ingredient_id=key, quantity=int(row["quantity"])))
            db.flush()
            db.merge(IngredientPrice(ingredient_id=key, price_pkr=int(row["price_pkr"])))
    for key, name, category, minutes, traditional, protein, amounts, steps in json.loads(
        (DATA / "recipes.json").read_text()
    ):
        db.merge(Recipe(id=key, name=name, category=category, servings=4, minutes=minutes,
                        instructions=steps, traditional=traditional, protein_rich_ingredients=protein))
        db.flush()
        for ingredient, amount in amounts.items():
            db.merge(RecipeIngredient(recipe_id=key, ingredient_id=ingredient, quantity=amount))
    db.commit()


if __name__ == "__main__":
    with Session(engine) as db:
        load_seed(db)
