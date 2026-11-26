from collections import Counter
from fractions import Fraction
from heapq import heapify, heappop, heappush

from ortools.sat.python import cp_model

from .schemas import Batch, BasketItem, IngredientInfo, Meal, PlanError, PlanRequest, PlanResponse, RecipeInfo, ShoppingList

BLOCKED = {
    "no_beef": {"beef"}, "no_chicken": {"chicken"}, "vegetarian": {"beef", "chicken"},
    "no_eggs": {"eggs"}, "no_dairy": {"dairy"},
}
UNIT_FACTORS = {"g": ("g", 1), "kg": ("g", 1000), "ml": ("ml", 1), "l": ("ml", 1000),
                "count": ("count", 1)}


def ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


def normalize(quantity: int, unit: str) -> tuple[int, str]:
    base, factor = UNIT_FACTORS[unit]
    return quantity * factor, base


def scale(recipe: RecipeInfo, people: int, catalog: dict[str, IngredientInfo]) -> Batch:
    amounts = []
    cost = Fraction(0)
    for line in recipe.ingredients:
        quantity, unit = normalize(line.quantity, line.unit)
        item = catalog[line.id]
        if unit != item.unit:
            raise ValueError(f"Incompatible units for {line.id}")
        scaled = ceil_div(quantity * people, recipe.servings)
        amounts.append(line.model_copy(update={"quantity": scaled, "unit": unit}))
        cost += Fraction(scaled * item.package_price_pkr * 100, item.package_quantity)
    return Batch(**(recipe.model_dump() | {"servings": people, "ingredients": amounts,
                                          "cost_paisa": round(cost)}))


def basket(counts: list[int], batches: list[Batch], catalog: dict[str, IngredientInfo]) -> list[BasketItem]:
    needed = Counter()
    for count, batch in zip(counts, batches, strict=True):
        if count:
            for line in batch.ingredients:
                needed[line.id] += count * line.quantity
    items = []
    for key, quantity in needed.items():
        item = catalog[key]
        packs = ceil_div(quantity, item.package_quantity)
        items.append(BasketItem(id=key, name=item.name, category=item.category, unit=item.unit, quantity=quantity,
                                package_quantity=item.package_quantity, packages=packs,
                                purchase_quantity=packs * item.package_quantity,
                                cost_pkr=packs * item.package_price_pkr))
    return sorted(items, key=lambda item: (item.category, item.name))


def solve(model: cp_model.CpModel):
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_deterministic_time = 0.65
    solver.parameters.max_time_in_seconds = 5
    return solver, solver.solve(model)


def generate(plan_id: str, request: PlanRequest, recipes: list[RecipeInfo],
             catalog: dict[str, IngredientInfo]) -> PlanResponse | PlanError:
    blocked = set().union(*(BLOCKED[key] for key in request.restrictions))
    batches = [scale(recipe, request.household_size, catalog) for recipe in recipes
               if blocked.isdisjoint(recipe.dietary_flags)]
    if not batches:
        return PlanError(status="infeasible", code="no_recipes",
                         message="The recipe catalog has no meals that match those restrictions.")

    slots = request.days * 2
    model = cp_model.CpModel()
    counts = [model.new_int_var(0, slots, f"count_{batch.id}") for batch in batches]
    model.add(sum(counts) == slots)
    by_ingredient = {}
    for count, batch in zip(counts, batches, strict=True):
        for line in batch.ingredients:
            by_ingredient.setdefault(line.id, []).append((line.quantity, count))
    cost_terms = []
    for key, usage in by_ingredient.items():
        item = catalog[key]
        upper = ceil_div(slots * max(amount for amount, _ in usage), item.package_quantity)
        packs = model.new_int_var(0, upper, f"packs_{key}")
        total = sum(amount * count for amount, count in usage)
        model.add(total <= packs * item.package_quantity)
        model.add(total >= (packs - 1) * item.package_quantity + 1)
        cost_terms.append(packs * item.package_price_pkr)
    cost = sum(cost_terms)
    affordable = model.new_bool_var("affordable")
    model.add(cost <= request.budget_pkr).only_enforce_if(affordable)
    model.add_assumption(affordable)

    quality_terms = []
    categories = {}
    for batch, count in zip(batches, counts, strict=True):
        used = model.new_bool_var(f"used_{batch.id}")
        model.add(count >= used)
        model.add(count <= slots * used)
        categories.setdefault(batch.category, []).append(used)
        repeated = model.new_int_var(0, slots - 2, f"extra_{batch.id}")
        model.add(repeated >= count - 2)
        matches = sum((
            "traditional" in request.preferences and batch.traditional,
            "quick" in request.preferences and batch.minutes <= 30,
        ))
        quality_terms.append(4 * used + matches * count - repeated)

    for category, used_recipes in categories.items():
        covered = model.new_bool_var(f"covered_{category}")
        model.add_max_equality(covered, used_recipes)
        quality_terms.append(2 * covered)

    # One quality point outweighs any cost difference between affordable plans.
    quality = sum(quality_terms)
    model.minimize(cost - (request.budget_pkr + 1) * quality)
    solver, status = solve(model)
    if status == cp_model.INFEASIBLE:
        model.clear_assumptions()
        model.minimize(cost)
        cheapest, result = solve(model)
        minimum = int(cheapest.objective_value) if result == cp_model.OPTIMAL else None
        message = "The sample-price basket cannot fit this budget. Try fewer days or a higher budget."
        if minimum is not None:
            message = f"The least expensive matching basket is PKR {minimum:,} at sample prices."
        return PlanError(status="infeasible", code="budget_too_low", message=message, minimum_budget_pkr=minimum)
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return PlanError(status="unavailable", code="planner_timeout",
                         message="The planner could not finish. Try a shorter plan or a higher budget.")

    selected = [solver.value(count) for count in counts]
    items = basket(selected, batches, catalog)
    total = sum(item.cost_pkr for item in items)
    if total > request.budget_pkr or total != solver.value(cost):
        raise RuntimeError("Optimized and calculated basket costs disagree")
    queue = [(-count, index) for index, count in enumerate(selected) if count]
    heapify(queue)
    previous = None
    meals = []
    for position in range(slots):
        if not queue:
            queue.append(previous)
            previous = None
        remaining, index = heappop(queue)
        if previous is not None:
            heappush(queue, previous)
        previous = (remaining + 1, index) if remaining < -1 else None
        meals.append(Meal(day=position // 2 + 1, slot="lunch" if position % 2 == 0 else "dinner",
                          batch=batches[index]))
    return PlanResponse(id=plan_id, request=request, meals=meals, remaining_budget_pkr=request.budget_pkr - total,
                        shopping_list=ShoppingList(plan_id=plan_id, total_cost_pkr=total, items=items))
