import os
from collections import Counter

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import catalog
from app.db import engine, session
from app.main import app
from app.models import Base, PlannedMeal
from app.planner import basket, generate, normalize, scale
from app.schemas import Amount, IngredientInfo, PlanRequest, PlanResponse, RecipeInfo
from app.seed import load_seed


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    if os.getenv("TEST_POSTGRES") == "1":
        command.upgrade(Config("alembic.ini"), "head")
        db_engine = engine
    else:
        db_engine = create_engine(f"sqlite:///{tmp_path_factory.mktemp('meal') / 'test.db'}")
        Base.metadata.create_all(db_engine)
    with Session(db_engine) as db:
        load_seed(db)
        load_seed(db)
    yield db_engine
    db_engine.dispose()


@pytest.fixture
def client(database):
    def test_session():
        with Session(database) as db:
            yield db

    app.dependency_overrides[session] = test_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_scaling_and_units(database):
    with Session(database) as db:
        items = catalog.ingredients(db)
        recipe = next(row for row in catalog.recipes(db, items) if row.id == "chana")
    assert normalize(2, "kg") == (2000, "g")
    assert normalize(2, "l") == (2000, "ml")
    one, five = (scale(recipe, people, items) for people in (1, 5))
    assert one.servings == 1 and five.servings == 5
    assert {line.id: line.quantity for line in one.ingredients}["chana"] == 75
    assert {line.id: line.quantity for line in five.ingredients}["lemon"] == 2
    merged = {line.id: line for line in basket([2], [five], items)}
    assert merged["chana"].quantity == 750
    assert merged["chana"].packages == 2
    assert merged["chana"].purchase_quantity == 1000
    assert merged["chana"].cost_pkr == 520


@pytest.mark.parametrize("days,people", [(3, 1), (5, 4), (7, 10)])
def test_generate_and_retrieve(client, database, days, people):
    response = client.post("/meal-plans/generate", json={
        "days": days, "household_size": people, "budget_pkr": 30000,
        "restrictions": ["vegetarian", "no_eggs", "no_dairy"], "preferences": ["quick"],
    })
    assert response.status_code == 201, response.json()
    plan = response.json()
    meals = plan["meals"]
    assert [(meal["day"], meal["slot"]) for meal in meals] == [
        (day, slot) for day in range(1, days + 1) for slot in ("lunch", "dinner")
    ]
    totals = Counter()
    for meal in meals:
        batch = meal["batch"]
        assert batch["servings"] == people
        assert not set(batch["dietary_flags"]) & {"chicken", "beef", "eggs", "dairy"}
        for line in batch["ingredients"]:
            totals[line["id"]] += line["quantity"]
    shopping = plan["shopping_list"]
    assert {line["id"]: line["quantity"] for line in shopping["items"]} == totals
    assert shopping["price_basis"] == "illustrative_sample"
    prices = {item["id"]: item["package_price_pkr"] for item in client.get("/ingredients").json()}
    for line in shopping["items"]:
        assert line["purchase_quantity"] == line["packages"] * line["package_quantity"]
        assert 0 <= line["purchase_quantity"] - line["quantity"] < line["package_quantity"]
        assert line["cost_pkr"] == prices[line["id"]] * line["packages"]
    total = sum(line["cost_pkr"] for line in shopping["items"])
    assert total == shopping["total_cost_pkr"] <= 30000
    assert plan["remaining_budget_pkr"] == 30000 - total
    path = f"/meal-plans/{plan['id']}"
    assert client.get(path).json() == plan
    assert client.get(f"{path}/shopping-list").json() == shopping
    with Session(database) as db:
        assert db.get(PlannedMeal, (plan["id"], len(meals) - 1)).batch == meals[-1]["batch"]


def test_api_errors_and_catalog(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert len(client.get("/ingredients").json()) >= 25
    assert len(client.get("/recipes").json()) >= 15
    assert client.get("/recipes/karahi").json()["name"] == "Chicken karahi with roti"
    assert client.get("/recipes/missing").status_code == 404
    assert client.post("/meal-plans/generate", json={"days": 4}).status_code == 422
    request = {"days": 3, "household_size": 1, "budget_pkr": 1}
    response = client.post("/meal-plans/generate", json=request)
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "budget_too_low"
    if body["minimum_budget_pkr"]:
        request["budget_pkr"] = body["minimum_budget_pkr"]
        assert client.post("/meal-plans/generate", json=request).status_code == 201


def test_planner_pays_for_variety_but_not_an_equivalent_upgrade():
    ingredients = {
        key: IngredientInfo(id=key, name=key, category="Test", unit="count", restriction=None,
                            package_quantity=6, package_price_pkr=price)
        for key, price in (("lentils", 50), ("rice", 900), ("premium_rice", 1000))
    }

    def dish(key, category, ingredient):
        return RecipeInfo(id=key, name=key, category=category, servings=1, minutes=30,
                          instructions=[], dietary_flags=[], traditional=True,
                          protein_rich_ingredients=False,
                          ingredients=[Amount(id=ingredient, name=ingredient, unit="count", quantity=1)])

    recipes = [dish("daal", "Lentils", "lentils"), dish("pulao", "Rice", "rice"),
               dish("premium_pulao", "Rice", "premium_rice")]

    def plan(budget):
        result = generate("test", PlanRequest(days=3, household_size=1, budget_pkr=budget),
                          recipes, ingredients)
        assert isinstance(result, PlanResponse)
        return result

    tight = plan(100)
    assert {meal.batch.id for meal in tight.meals} == {"daal"}
    room = plan(1100)
    assert {meal.batch.id for meal in room.meals} == {"daal", "pulao"}
    assert room.shopping_list.total_cost_pkr == 950
    assert room.remaining_budget_pkr == 150
