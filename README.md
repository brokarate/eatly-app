# Project Meal

Project Meal plans family-style Pakistani lunches and dinners against a total grocery budget. It uses a seeded catalog of 15 recipes and 27 ingredients. All prices are illustrative sample data in PKR.

## Downloads

- Full [Xcode](https://developer.apple.com/xcode/) and one iOS Simulator runtime. Open Xcode to finish first-launch setup and install an iOS runtime from Settings → Components. Choose a release compatible with your macOS version.
- Docker Desktop with Docker Compose. Start Docker Desktop and wait for the engine to be ready. The first Compose build pulls the PostgreSQL and Python base images and installs Python dependencies in the API image.

The Compose workflow supplies Python 3.12, PostgreSQL, FastAPI, Pydantic, SQLAlchemy, Alembic, OR-Tools and pytest. The Xcode project uses system SwiftUI and Foundation.

## Run the database and API

From the app folder:

```sh
docker compose up -d --build --wait
docker compose logs -f api
```

The API startup command applies migrations, loads the sample catalog, and starts Uvicorn. PostgreSQL data lives in the named Compose volume. To run migrations and seed manually against an already running database:

```sh
docker compose up -d --wait db
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.seed
```

The optional `.env.example` documents local environment overrides. Copy it to `.env` before changing PostgreSQL initialization settings on a fresh database. Keep the API local. It accepts requests without accounts.

```sh
curl --fail http://127.0.0.1:8000/health
curl --fail-with-body http://127.0.0.1:8000/meal-plans/generate \
  -H 'Content-Type: application/json' \
  -d '{"budget_pkr":8000,"household_size":4,"days":3,"restrictions":["no_beef"],"preferences":["quick"]}'
```

FastAPI’s interactive OpenAPI interface is at [localhost:8000/docs](http://127.0.0.1:8000/docs). It lists the health, ingredient, recipe, generate, retrieve and shopping-list endpoints. A proven budget failure returns HTTP 409. A solver run that ends without finding a feasible plan or proving infeasibility returns HTTP 503.

## Run on an iPhone Simulator

1. Open `ios/ProjectMeal.xcodeproj` in Xcode.
2. Select the ProjectMeal scheme and an iPhone simulator, then press Run.
3. Leave the app’s backend address at `http://127.0.0.1:8000` for Docker on the same Mac.
4. Generate a plan with the defaults. Tap a meal for batch quantities and cooking instructions, then open Shopping list to see the consolidated purchases. The app keeps the latest plan and shopping checkmarks locally.
5. Use Plan to edit preferences and generate again, or Week to reopen the latest plan. Week starts with a tappable seven-day strip, then shows the checkout estimate, budget left and day-by-day meals. Newly generated plans start on the device’s current date. Profile stores an editable avatar, name, username, city and bio locally. Its Appearance setting offers System, Light and Dark. Try PKR 1 to see a structured budget failure.

## Browse the catalog

Browse loads recipes and ingredients from the same backend used for planning. Recipe searches match names, categories and ingredient names. Ingredient searches match names and categories. Catalog prices are illustrative sample prices. Tap the heart on a recipe or ingredient to save it in Profile → Favorites. Swipe across any main tab to switch to its neighbor.

Artwork falls back to category illustrations. Add an image asset to the app target named `recipe-<recipe-id>` or `ingredient-<ingredient-id>` to replace its placeholder across the app.

## Test on a physical iPhone

Enable Developer Mode on the iPhone and use your signing team in Xcode. Connect the Mac and iPhone to the same Wi-Fi. Set the Mac's private Wi-Fi IPv4 address when starting the API, for example:

```sh
MEAL_LAN_ADDRESS=192.168.0.29 docker compose -f compose.yaml -f compose.lan.yaml up -d --wait
```

In Project Meal on the iPhone, open Plan → Developer settings and set the backend address to the Mac address with port 8000, such as `http://192.168.0.29:8000`. Allow local network access when prompted. Run `docker compose up -d --wait` to return to loopback-only access after testing.

## Tests

```sh
docker compose run --rm -e TEST_POSTGRES=1 api python -m pytest -q
```

This exercises the migrations, repeat seed, optimizer, API, and persistence with the local development database. To use isolated SQLite for API and optimizer tests, omit `-e TEST_POSTGRES=1`. Tests cover 3-, 5- and 7-day plans, quantity scaling, unit normalization, restriction enforcement, package rounding and reconciliation, retrieval, and invalid requests.

For the iOS end-to-end tests, keep the local API running, open the shared ProjectMeal scheme, select an iPhone simulator, and choose Product → Test in Xcode. The UI tests exercise a live meal plan, recipe details, persisted shopping checkmarks, and an infeasible budget.

## How estimates work

Every recipe has a four-person reference batch. The planner assumes equal appetites and rounds up each batch ingredient to whole grams, millilitres, or pieces. Vegetarian excludes meat and allows eggs and dairy unless separately restricted. The recipes include the listed accompaniments in their cost. Chana's cooking time excludes overnight soaking.

CP-SAT chooses integer recipe counts totalling two meals per day. For every ingredient it sums all batch requirements before rounding up to whole purchase packages. Each item has one fixed sample package size. The optimizer enforces the whole-basket budget. Each distinct recipe earns four quality points, each distinct recipe category earns two, each requested traditional or quick match earns one per meal, and repeats beyond two uses lose one each. Basket cost breaks ties between plans with the same quality score. Older requests can still contain the retired protein preference, which has no effect on new plans. The planner interleaves the selected counts to avoid adjacent repeats where possible. Searches use one worker and a time limit. A feasible result can be returned before optimality is proved. The app shows a minimum budget only if the solver proves it.

Meal cards estimate ingredients consumed, using per-unit prices rounded for display. The shopping screen prices the full packages purchased, including pantry staples. Water is omitted from pricing. The app plans lunches and dinners only. Pantry inventory, leftovers, measured nutrition and store-specific prices are outside this prototype.

## Structure

```text
app/
├── compose.yaml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/              migration environment and initial schema
│   ├── app/                  API, schemas, database, seed, catalog and planner
│   └── tests/                optimizer, API and persistence tests
├── data/                     sample ingredient packages, prices and recipes
└── ios/                      SwiftUI, API client, Info.plist and Xcode project
```

## Retailer data collector

The collector lives in bot/ alongside ios/ and backend/. See [the collector setup guide](bot/README.md) for sources, daily updates, exports, historical prices, and the /market API. Existing meal generation continues to use the illustrative seed prices until real products are reviewed and mapped to ingredients.
