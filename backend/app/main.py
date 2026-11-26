from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import catalog, planner
from .db import session
from .models import Plan, PlannedMeal
from .market import router as market_router
from .schemas import IngredientInfo, PlanError, PlanRequest, PlanResponse, RecipeInfo, ShoppingList

app = FastAPI(title="Project Meal", version="0.1.0")
Database = Annotated[Session, Depends(session)]
app.include_router(market_router)


@app.get("/health")
def health(db: Database):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/ingredients")
def ingredients(db: Database) -> list[IngredientInfo]:
    return list(catalog.ingredients(db).values())


@app.get("/recipes")
def recipes(db: Database) -> list[RecipeInfo]:
    return catalog.recipes(db, catalog.ingredients(db))


@app.get("/recipes/{recipe_id}")
def recipe_detail(recipe_id: str, db: Database) -> RecipeInfo:
    for recipe in recipes(db):
        if recipe.id == recipe_id:
            return recipe
    raise HTTPException(404, detail={"code": "recipe_not_found", "message": "Recipe not found."})


@app.post("/meal-plans/generate", status_code=201, response_model=PlanResponse,
          responses={409: {"model": PlanError}, 503: {"model": PlanError}})
def create_plan(request: PlanRequest, db: Database):
    ingredients_by_id = catalog.ingredients(db)
    result = planner.generate(str(uuid4()), request, catalog.recipes(db, ingredients_by_id), ingredients_by_id)
    if isinstance(result, PlanError):
        return JSONResponse(status_code=409 if result.status == "infeasible" else 503,
                            content=result.model_dump())
    db.add(Plan(id=result.id, request=request.model_dump(), snapshot=result.model_dump()))
    db.flush()
    db.add_all(PlannedMeal(plan_id=result.id, position=position, recipe_id=meal.batch.id,
                           batch=meal.batch.model_dump()) for position, meal in enumerate(result.meals))
    db.commit()
    return result


@app.get("/meal-plans/{plan_id}")
def get_plan(plan_id: UUID, db: Database) -> PlanResponse:
    plan = db.get(Plan, str(plan_id))
    if plan is None:
        raise HTTPException(404, detail={"code": "plan_not_found", "message": "Meal plan not found."})
    return PlanResponse.model_validate(plan.snapshot)


@app.get("/meal-plans/{plan_id}/shopping-list")
def shopping_list(plan_id: UUID, db: Database) -> ShoppingList:
    return get_plan(plan_id, db).shopping_list
