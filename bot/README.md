# Project Meal grocery collector

The bot and iOS app share the same app directory. The bot uses Python's standard library and stores its runtime data in data/catalog. It reads public pages and feeds with a declared user agent, robots checks, rate limits, bounded retries, and HTTPS domain restrictions.

## Collect now

Run from the app directory with Python 3.12 or newer.

```sh
python3 -m bot.collect --max-pages 1000
```

Select sources or use a small initial pass.

```sh
python3 -m bot.collect --sources alfatah,metro,imtiaz --max-pages 20
python3 -m bot.collect --sources naheed --max-pages 20
```

The page budget applies independently to each retailer and includes discovery pages. The default is 1000 requests per source per cycle. For feeds or catalogs larger than the budget, the run is explicitly partial. Public page collectors rotate through discovered product URLs using a persisted checkpoint. Shopify refreshes up to 100 bulk feed pages each cycle, then discovers additional products through product sitemaps. Missing products are prioritised; already saved products outside the bulk feed rotate for price refreshes. Al-Fatah supports up to 256 sitemaps and uses a three-second request interval. Individual product requests stop on a rate or access block. HTTP 429 backoff is saved under data/catalog/cooldowns and survives worker restarts. Numeric and HTTP-date Retry-After values are respected; an unspecified delay defaults to 15 minutes. Coverage remains partial until all discovered URLs are processed. Increase the page budget for a more extensive crawl, for example --max-pages 50000. That can take hours because requests remain rate limited.

To recover missing Al-Fatah listings without repeating its bulk refresh first, run the following while the daily worker is stopped. The existing collector lock prevents overlapping writers.

```sh
python3 -m bot.collect --sources alfatah --shopify-sitemap-only --max-pages 1000
```

## Run every 24 hours with Docker

```sh
docker compose -f compose.yaml -f compose.catalog.yaml up -d --build
docker compose -f compose.yaml -f compose.catalog.yaml logs -f collector
```

This starts a collection immediately and schedules subsequent cycles at 24-hour intervals from the previous cycle start. An overlong run finishes before the next starts. The collector restarts with Docker Desktop. The Mac and Docker must stay running for scheduled work to execute.

For the existing iPhone Wi-Fi setup, include the LAN overlay and the Mac's current private address.

```sh
MEAL_LAN_ADDRESS=192.168.0.29 docker compose -f compose.yaml -f compose.lan.yaml -f compose.catalog.yaml up -d --build
```

Update the IP if the Mac changes networks. This uses the existing local PostgreSQL and API services and adds a separate collector service. The collector database is mounted into the API for reading.

## Dataset

- catalog.sqlite3 contains current products, historical observations, source runs, and continuation checkpoints.
- products.jsonl and products.csv are atomically replaced exports of the current products after each source finishes.
- last-run.json records coverage, failures, counts, and completion times.
- raw/<source>/<sha256>.gz stores exact public responses used as evidence.

Product records contain source, source product or variant ID, title, category, SKU or barcode when supplied, source URL, image URL, package quantity and normalized unit, integer price in paisa, currency, source availability, location scope, nutrition, observation time, and evidence reference.

The identity combines retailer, variant, and store scope. Products with similar names from different stores remain separate offers. A category or name alone cannot establish identical products.

Prices represent the public listing at the observation time. A missing price is null. Availability is null unless explicitly supplied. A product disappearing from a crawl is not treated as out of stock. Older records remain in the dataset with their original observation date. The API marks observations older than 36 hours stale. History retains the product record from each run, including its price, size, location, and nutrition.

Package normalization accepts explicit grams, kilograms, millilitres, litres, pieces, and clear multipacks. Ambiguous ranges and mixed sizes remain unnormalized. Shipping weights are excluded.

Nutrition stores published label data and its serving basis. Numeric macros are parsed from structured NutritionInformation or explicitly labelled text with a basis. Marketing descriptions may be retained as raw text with empty numeric macros. Missing nutrition remains null. Recipe nutrition and generic food composition cannot substitute for a manufacturer's label.

## Sources

- Al-Fatah uses its public paginated Shopify product feed, including each size variant, then its product sitemaps and individual product JSON for listings beyond the bulk feed limit. It does not request feed pages beyond the 25,000-product depth. Currency is PKR for this Pakistan storefront. The vendor field is stored separately from manufacturer brand. This feed often lacks a confirmed branch or city.
- METRO parses schema.org product offers and public server-rendered store variants. Where published, the store ID, branch, city, effective price, availability, and package weight are captured together. Its sitemap supplies additional product pages.
- Imtiaz uses its public product sitemaps and schema.org Product pages. The current public pages can expose prices even though the storefront asks for a delivery area. Prices without an explicit branch stay location unspecified.
- Jalal Sons uses its public product sitemaps and schema.org Product pages with the same location rules.
- Naheed uses its published public media sitemap and schema.org Product pages.
- pandamart collects public store catalogs for six Lahore area targets. It verifies VendorData code and city on each page before accepting product prices, and rejects recommendations whose vendor code differs. Store codes are gu85 for DHA Phase 5, lxyu for Johar Town, dcu3 for DHA Phase 6, btqk for DHA Y Block, h8wc for Model Town, and d74x for Allama Iqbal Town. The public DHA Phase 5 page may expose no products. Any HTTP 403 or identity mismatch is logged per target.
- Each pandamart record separates the configured delivery_area from the source-confirmed store_id, branch and store coordinates. delivery_confirmed stays false because a public store catalog does not verify service to a particular street address. The storage key includes both store and area context so one store's prices cannot overwrite another's.

Source configuration lives in bot/sources.json. A location-specific public catalog can be added through start_urls on a pages adapter. Location fields must be obtained from the record or a separately verified source configuration. An access block, CAPTCHA, login requirement, or robots restriction is reported as a source error and left for a permitted feed or access method.

## API

The existing FastAPI backend exposes the collected dataset.

```text
GET /market/products?q=rice&source=imtiaz&priced_only=true&limit=50&offset=0
GET /market/products?city=Lahore&source=metro
GET /market/products?source=pandamart&city=Lahore&area=Johar%20Town&store_id=lxyu
GET /market/locations?source=pandamart
GET /market/sources
GET /market/products/{product_id}/history
```

/market/locations reports each configured area, actual store identity, latest request status, and saved product count. /market/sources reports each source's latest status and coverage. Successful records can be retained from a partially completed run. Country PK does not imply Lahore. Products with no confirmed city are excluded from city filters.

The meal planner still uses its illustrative seed prices. Linking an ingredient such as rice to a real retailer SKU requires a reviewed product match, household location, and treatment of missing or stale prices. The market endpoints supply the data for that next step.

## Verification

```sh
python3 -m unittest discover -s bot/tests -v
docker compose run --rm -e TEST_POSTGRES=1 api python -m pytest -q
```

Tests use small deterministic fixtures and isolated databases. The first command checks normalization, source parsing, effective price and store extraction, history, duplicate writes, failed sources, and partial runs. The backend tests also check catalog search, literal search escaping, location filters, stale flags, pagination, and history retrieval.
