"""Store-scoped extraction from public foodpanda HTML, without executing site scripts."""
import json
from urllib.parse import urljoin, urlsplit, urlunsplit

from .adapters import PageParser, extract_description_nutrition, walk
from .http import BudgetReached, FetchError
from .normalize import package_size, plain_text, price_paisa
from .store import checkpoint, now


def apollo_state(page):
    for _, script in page.scripts:
        marker = "{apollo:"
        if marker not in script:
            continue
        try:
            value, _ = json.JSONDecoder().raw_decode(script[script.index(marker) + len(marker):])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("initialState"), dict):
            return value["initialState"]
    return {}


def inspect_store(html, target):
    page = PageParser()
    page.feed(html)
    state = apollo_state(page)
    expected = target["store_id"]
    vendors = [item for item in walk(state) if item.get("__typename") == "VendorData"]
    vendor = next((item for item in vendors if str(item.get("code")) == expected), None)
    if vendor is None:
        raise FetchError(f"Page does not confirm requested store {expected}; no prices saved")
    location = vendor.get("location") or {}
    city = (location.get("city") or {}).get("name")
    if not city or city.casefold() != target["city"].casefold():
        raise FetchError(f"Store {expected} does not confirm city {target['city']}; no prices saved")
    if not vendor.get("name"):
        raise FetchError("Store name is missing")
    details = {
        "city": city, "branch": vendor["name"], "store_id": expected,
        "delivery_area": target["area"], "target_id": target["id"],
        "delivery_confirmed": False, "scope": "source_store_catalog",
        "note": "Store identity is verified in the public page. Delivery to a specific street address is unverified.",
        "store_latitude": location.get("latitude"), "store_longitude": location.get("longitude"),
        "store_status": (vendor.get("availability") or {}).get("status"),
        "store_url": target["url"],
    }
    return page, state, details


def records(html, target, url):
    page, state, location = inspect_store(html, target)
    for item in walk(state):
        if item.get("__typename") != "GroceryProductData":
            continue
        # Normalized page data can include recommendations from other vendors.
        if str(item.get("vendorCode")) != target["store_id"]:
            continue
        identifier = str(item.get("id") or "")
        name = plain_text(item.get("name"))
        if not identifier or not name:
            continue
        category_info = item.get("categoryLevelInfo") or {}
        if not isinstance(category_info, dict):
            category_info = {}
        images = item.get("urls") or []
        attributes = item.get("attributes") or {}
        yield {
            "external_id": identifier, "name": name, "variant": None,
            "global_catalog_id": item.get("globalCatalogID"), "sku": item.get("sku"),
            "brand": None, "barcode": None, "category": category_info.get("name"),
            "url": target["url"].rstrip("/") + "/product/" + identifier,
            "listing_url": url, "image_url": images[0] if images else None,
            "description": plain_text(item.get("description")), "package": package_size(name),
            "currency": "PKR", "price_paisa": price_paisa(item.get("price")),
            "available": item.get("isAvailable") if isinstance(item.get("isAvailable"), bool) else None,
            "nutrition": extract_description_nutrition(item.get("description")),
            "source_food_labelling": attributes.get("foodLabelling"),
            "location": location,
            "extraction": "foodpanda public Apollo GroceryProductData with verified VendorData",
            "price_fields": {"price": item.get("price"), "originalPrice": item.get("originalPrice"),
                             "containerPrice": item.get("containerPrice")},
        }


def category_urls(page, target):
    prefix = urlsplit(target["url"]).path.rstrip("/") + "/category/"
    result = []
    for href in page.links:
        parts = urlsplit(urljoin(target["url"], href))
        if parts.hostname == "www.foodpanda.pk" and parts.path.startswith(prefix):
            result.append(urlunsplit(("https", parts.netloc, parts.path, "", "")))
    return sorted(set(result))


def save_location(db, run_id, source, target, status, count, details=None, error=None):
    location_details = {"identity_verified": details is not None,
                        "expected_store_name": target["expected_name"],
                        "delivery_confirmed": False} | (details or {})
    db.execute("""
        INSERT INTO collection_locations
          (source,target_id,area,city,store_id,branch,url,status,checked_at,run_id,records,error,details)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source,target_id) DO UPDATE SET
          area=excluded.area,city=excluded.city,store_id=excluded.store_id,branch=excluded.branch,
          url=excluded.url,status=excluded.status,checked_at=excluded.checked_at,run_id=excluded.run_id,
          records=excluded.records,error=excluded.error,details=excluded.details
    """, (source["id"], target["id"], target["area"], target["city"], target["store_id"],
          (details or {}).get("branch"), target["url"], status, now(),
          run_id, count, error, json.dumps(location_details)))
    db.commit()


def collect(client, source, db, emit, report, run_id):
    targets = source["locations"]
    if client.max_pages < len(targets):
        raise FetchError(f"Pandamart needs at least {len(targets)} pages to check every configured area")
    allowance = max(1, client.max_pages // len(targets))
    results = []
    for target in targets:
        count = set()
        details = None
        start_pages = client.pages
        errors = []
        status = "partial"
        coverage = "store_catalog_batch"
        save_location(db, run_id, source, target, "running", 0)
        try:
            html = client.get(target["url"])
            page, _, details = inspect_store(html, target)

            def ingest(document, url):
                for record in records(document, target, url):
                    emit(record)
                    count.add(record["external_id"])

            ingest(html, target["url"])
            urls = category_urls(page, target)
            offset = int(checkpoint(db, source["id"], "category_offset:" + target["id"]) or "0")
            if urls:
                offset %= len(urls)
            visited = 0
            for index in range(len(urls)):
                if client.pages - start_pages >= allowance:
                    break
                position = (offset + index) % len(urls)
                try:
                    document = client.get(urls[position])
                    ingest(document, urls[position])
                except BudgetReached:
                    break
                except FetchError as error:
                    errors.append(str(error))
                    if len(errors) >= 3:
                        break
                visited += 1
                checkpoint(db, source["id"], "category_offset:" + target["id"], (position + 1) % len(urls))
            if not count:
                status, coverage = "no_catalog_data", "store_verified_without_products"
            elif visited == len(urls) and not errors:
                status, coverage = "success", "public_categories_visited"
            # Category pages can paginate client-side. Visiting their HTML is not full-catalog coverage.
            save_location(db, run_id, source, target, status, len(count), details, "; ".join(errors) or None)
        except FetchError as error:
            errors.append(str(error))
            status, coverage = "error", "store_not_verified"
            save_location(db, run_id, source, target, status, len(count), details, str(error))
        result = {"target_id": target["id"], "area": target["area"], "store_id": target["store_id"],
                  "branch": (details or {}).get("branch"), "status": status,
                  "records": len(count), "pages": client.pages - start_pages, "coverage": coverage,
                  "delivery_confirmed": False, "errors": errors}
        results.append(result)
    report["locations"] = results
    report["coverage"] = "store_catalog_batches"
    report["errors"].extend(error for result in results for error in result["errors"])
