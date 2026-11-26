from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Restriction = Literal["no_beef", "no_chicken", "vegetarian", "no_eggs", "no_dairy"]
Preference = Literal["traditional", "quick", "high_protein"]


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    budget_pkr: int = Field(ge=1, le=1_000_000)
    household_size: int = Field(ge=1, le=10)
    days: Literal[3, 5, 7]
    restrictions: list[Restriction] = Field(default_factory=list, max_length=5)
    preferences: list[Preference] = Field(default_factory=list, max_length=3)


class IngredientInfo(BaseModel):
    id: str
    name: str
    category: str
    unit: str
    restriction: str | None
    package_quantity: int
    package_price_pkr: int
    price_basis: Literal["illustrative_sample"] = "illustrative_sample"


class Amount(BaseModel):
    id: str
    name: str
    unit: str
    quantity: int


class RecipeInfo(BaseModel):
    id: str
    name: str
    category: str
    servings: int
    minutes: int
    instructions: list[str]
    ingredients: list[Amount]
    dietary_flags: list[str]
    traditional: bool
    protein_rich_ingredients: bool


class Batch(RecipeInfo):
    cost_paisa: int


class Meal(BaseModel):
    day: int
    slot: Literal["lunch", "dinner"]
    batch: Batch


class BasketItem(Amount):
    category: str
    package_quantity: int
    packages: int
    purchase_quantity: int
    cost_pkr: int


class ShoppingList(BaseModel):
    plan_id: str
    total_cost_pkr: int
    items: list[BasketItem]
    price_basis: Literal["illustrative_sample"] = "illustrative_sample"


class PlanResponse(BaseModel):
    id: str
    status: Literal["feasible"] = "feasible"
    request: PlanRequest
    meals: list[Meal]
    shopping_list: ShoppingList
    remaining_budget_pkr: int


class PlanError(BaseModel):
    status: Literal["infeasible", "unavailable"]
    code: str
    message: str
    minimum_budget_pkr: int | None = None
