import json
import re
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from .http import BudgetReached, FetchError
from .normalize import nutrition, package_size, plain_text, price_paisa
from .store import checkpoint


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.links = []
        self._script_attrs = None
        self._parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self._script_attrs, self._parts = attrs, []
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_data(self, data):
        if self._script_attrs is not None:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._script_attrs is not None:
            self.scripts.append((self._script_attrs, "".join(self._parts)))
            self._script_attrs = None


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def type_is(value, name):
    types = value.get("@type", [])
    return name in ([types] if isinstance(types, str) else types)


def scalar(value):
    if isinstance(value, list):
        return ", ".join(str(scalar(item)) for item in value if scalar(item) is not None)
    if isinstance(value, dict):
        return value.get("name") or value.get("value")
    return value


def product_record(product, url):
    offers = product.get("offers") or [{}]
    offers = offers if isinstance(offers, list) else [offers]
    for index, offer in enumerate(offers):
        if not isinstance(offer, dict):
            continue
        name = plain_text(product.get("name"))
        if not name:
            continue
        currency = offer.get("priceCurrency")
        price = price_paisa(offer.get("price")) if currency == "PKR" else None
        status = str(offer.get("availability", "")).rsplit("/", 1)[-1]
        available = {"InStock": True, "OutOfStock": False, "SoldOut": False}.get(status)
        images = product.get("image")
        if isinstance(images, list):
            images = images[0] if images else None
        if isinstance(images, dict):
            images = images.get("url") or images.get("contentUrl")
        external = str(product.get("sku") or product.get("productID") or product.get("@id") or url)
        if len(offers) > 1:
            external += ":" + str(offer.get("sku") or offer.get("@id") or index)
        location = None
        source_nutrition = product.get("nutrition") or extract_description_nutrition(product.get("description"))
        address = (offer.get("availableAtOrFrom") or {}).get("address") if isinstance(offer.get("availableAtOrFrom"), dict) else None
        if isinstance(address, dict) and address.get("addressLocality"):
            location = {"city": address["addressLocality"], "scope": "source_explicit"}
        yield {
            "external_id": external, "name": name, "variant": None,
            "brand": scalar(product.get("brand")), "category": scalar(product.get("category")),
            "sku": product.get("sku"), "barcode": product.get("gtin13") or product.get("gtin"),
            "url": url, "image_url": images, "description": plain_text(product.get("description")),
            "package": package_size(name), "currency": currency, "price_paisa": price,
            "available": available, "nutrition": nutrition(source_nutrition) if product.get("nutrition") else source_nutrition,
            "location": location, "extraction": "schema.org/Product",
            "price_fields": {key: offer[key] for key in ("price", "priceCurrency", "availability") if key in offer},
        }


def metro_record(value, url):
    name = value.get("product_display_name") or value.get("variant_name") or value.get("product_name")
    package = package_size(f"{value.get('variant_weight', '')} {value.get('variant_unit_type', '')}")
    return {
        "external_id": str(value["variant_id"]), "name": plain_text(name),
        "variant": value.get("variant_name"), "brand": value.get("product_brand_name"),
        "category": value.get("product_category_name"), "sku": value.get("variant_sku"),
        "barcode": value.get("variant_barcode"), "url": url,
        "image_url": value.get("variant_primary_image_url"),
        "description": plain_text(value.get("product_short_description")),
        "package": package, "currency": "PKR",
        "price_paisa": price_paisa(value.get("effective_price")),
        "available": value.get("is_in_stock") if isinstance(value.get("is_in_stock"), bool) else None,
        "nutrition": nutrition(value.get("product_nutritional_information")),
        "location": {
            "store_id": str(value["store_id"]), "branch": value.get("store_name"),
            "city": value.get("store_city_name"), "scope": "source_explicit",
        },
        "extraction": "METRO public server-rendered store variant",
        "price_fields": {key: value.get(key) for key in
                         ("effective_price", "price", "sale_price", "gross_sell_price", "sale", "in_promotion")},
    }


def parse_page(html, url, source_id):
    page = PageParser()
    page.feed(html)
    for attrs, body in page.scripts:
        if attrs.get("type") == "application/ld+json":
            try:
                document = json.loads(body)
            except json.JSONDecodeError:
                continue
            for item in walk(document):
                if type_is(item, "Product"):
                    yield from product_record(item, url)
    if source_id == "metro":
        chunks = []
        decoder = json.JSONDecoder()
        for _, body in page.scripts:
            for match in re.finditer(r"self\.__next_f\.push\(", body):
                try:
                    chunk, _ = decoder.raw_decode(body[match.end():])
                    if isinstance(chunk, list) and len(chunk) > 1 and isinstance(chunk[1], str):
                        chunks.append(chunk[1])
                except json.JSONDecodeError:
                    continue
        flight = "".join(chunks)
        for match in re.finditer(r'\{"store_variant_id"\s*:', flight):
            try:
                item, _ = decoder.raw_decode(flight[match.start():])
            except json.JSONDecodeError:
                continue
            if all(key in item for key in ("variant_id", "store_id", "product_name")):
                yield metro_record(item, url)


def shopify_records(document, base_url):
    for product in document["products"]:
        name = plain_text(product.get("title"))
        if not name:
            continue
        images = product.get("images") or []
        tags = product.get("tags") or []
        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
        barcode_tags = [tag.removeprefix("Barcode_") for tag in tags if tag.startswith("Barcode_")]
        for variant in product.get("variants", []):
            title = variant.get("title", "")
            size = package_size(title) if title != "Default Title" else None
            size = size or package_size(name)
            url = base_url + "/products/" + product["handle"] + "?variant=" + str(variant["id"])
            yield {
                "external_id": str(variant["id"]), "product_id": str(product["id"]), "name": name,
                "variant": title, "brand": None, "vendor": product.get("vendor"), "category": product.get("product_type"),
                "sku": variant.get("sku"), "barcode": variant.get("barcode") or (barcode_tags[0] if len(barcode_tags) == 1 else None),
                "url": url, "image_url": images[0].get("src") if images else None,
                "description": plain_text(product.get("body_html")), "tags": tags,
                "package": size, "currency": "PKR", "price_paisa": price_paisa(variant.get("price")),
                "available": variant.get("available") if isinstance(variant.get("available"), bool) else None,
                "nutrition": extract_description_nutrition(product.get("body_html")),
                "extraction": "Shopify public product variant",
                "source_updated_at": variant.get("updated_at") or product.get("updated_at"),
                "price_fields": {"price": variant.get("price"), "compare_at_price": variant.get("compare_at_price")},
            }


def extract_description_nutrition(html):
    if not html:
        return None
    page = PageParser()
    page.feed(html)
    for attrs, body in page.scripts:
        if attrs.get("type") == "application/ld+json":
            try:
                for item in walk(json.loads(body)):
                    if type_is(item, "NutritionInformation"):
                        return nutrition(item)
            except json.JSONDecodeError:
                pass
    text = plain_text(html)
    if re.search(r"nutrition|protein|carbohydrate|calories", text, re.I):
        # A whole description can contain marketing claims. Keep its text without inventing quantities.
        return nutrition(text)
    return None


SHOPIFY_MAX_FEED_PAGES = 100  # 250 products per page, at most 25,000 products.


def collect_shopify(client, source, db, emit, report):
    if source.get("sitemap_only"):
        return collect_shopify_sitemap(client, source, db, emit, report, set())
    # Refresh the bulk feed first. Its ordering can change when products are added.
    feed_urls = set()
    for page in range(1, SHOPIFY_MAX_FEED_PAGES + 1):
        url = source["base_url"] + f"/products.json?limit=250&page={page}"
        document = client.get_json(url)
        if not isinstance(document, dict) or not isinstance(document.get("products"), list):
            raise FetchError("Shopify product feed format changed")
        if not document["products"]:
            report["coverage"] = "all_feed_pages_read"
            return
        fingerprint = tuple(str(row.get("id")) for row in document["products"])
        if fingerprint == report.get("previous_page"):
            raise FetchError("Source repeated a product page; pagination stopped")
        report["previous_page"] = fingerprint
        for item in shopify_records(document, source["base_url"]):
            emit(item)
            feed_urls.add(item["url"].split("?", 1)[0])
    # Do not request page 101, which exceeds Shopify's pagination depth.
    report["feed_pagination_limit"] = True
    if not source.get("sitemaps"):
        report["coverage"] = "partial_rotating_batch"
        report["message"] = "Bulk feed depth reached; no product sitemap configured"
        return
    collect_shopify_sitemap(client, source, db, emit, report, feed_urls)


def collect_shopify_sitemap(client, source, db, emit, report, feed_urls):
    urls = sorted(set(url for url in sitemap_urls(client, source, report)
                      if product_url(url, client, source)))
    report["discovered_urls"] = len(urls)
    known = {row[0].split("?", 1)[0] for row in db.execute(
        "SELECT json_extract(record,'$.url') FROM products WHERE source=?", (source["id"],)) if row[0]}
    missing = [url for url in urls if url not in known and url not in feed_urls]
    refresh = [url for url in urls if url in known and url not in feed_urls]
    offset = int(checkpoint(db, source["id"], "shopify_refresh_offset") or "0")
    if refresh:
        offset %= len(refresh)
    # Newly discovered products first; saved products rotate for price refreshes.
    queue = [(url, None) for url in missing] + [
        (refresh[(offset + index) % len(refresh)], (offset + index + 1) % len(refresh))
        for index in range(len(refresh))]
    report["missing_urls_before_batch"] = len(missing)
    collected = 0
    missing_collected = 0
    consecutive_errors = 0
    report["coverage"] = "partial_rotating_batch"
    for url, next_offset in queue:
        if client.pages >= client.max_pages:
            break
        try:
            document = client.get_json(url + ".json")
            product = document.get("product") if isinstance(document, dict) else None
            if (not isinstance(product, dict) or not product.get("variants")
                    or product.get("handle") != urlsplit(url).path.rsplit("/", 1)[-1]):
                raise FetchError("Individual Shopify product format or identity changed")
            for item in shopify_records({"products": [product]}, source["base_url"]):
                emit(item)
            collected += 1
            missing_collected += next_offset is None
            consecutive_errors = 0
            if next_offset is not None:
                checkpoint(db, source["id"], "shopify_refresh_offset", next_offset)
        except BudgetReached:
            break
        except FetchError as error:
            report["errors"].append(str(error)[:400])
            consecutive_errors += 1
            # Do not continue other product requests after a rate or access block.
            if any(code in str(error) for code in ("HTTP 429", "HTTP 403")) or consecutive_errors >= 3:
                break
    report["sitemap_products_collected"] = collected
    report["missing_urls_after_batch"] = len(missing) - missing_collected
    # Failed requests must not count as successfully covered URLs.
    if urls and collected == len(queue) and not report["errors"]:
        report["coverage"] = "all_discovered_urls_visited"
    elif not urls:
        report["errors"].append("No product URLs found in Shopify sitemaps")
    prefix = "Sitemap recovery" if source.get("sitemap_only") else "Bulk feed refreshed"
    report["message"] = (f"{prefix}; {collected} sitemap products collected; "
                         f"{report['missing_urls_after_batch']} discovered products still missing")
    if report["errors"]:
        report["message"] += "; " + report["errors"][-1]


def sitemap_urls(client, source, report):
    """Recurse only through public same-retailer sitemaps, with bounded depth."""
    pending = [(url, 0) for url in source.get("sitemaps", [])]
    seen = set()
    found = []
    while pending:
        url, depth = pending.pop(0)
        if url in seen:
            continue
        if len(seen) >= source.get("max_sitemaps", 64) or depth > 5:
            report["errors"].append("Sitemap discovery limit reached")
            break
        seen.add(url)
        try:
            document = ET.fromstring(client.get(url))
        except BudgetReached:
            raise
        except (FetchError, ET.ParseError) as error:
            report["errors"].append(str(error)[:400])
            continue
        tag = document.tag.rsplit("}", 1)[-1]
        if tag not in ("sitemapindex", "urlset"):
            report["errors"].append("Unexpected sitemap XML format")
            continue
        for entry in document:
            location = next((child.text for child in entry if child.tag.rsplit("}", 1)[-1] == "loc"), None)
            if not location or not client.allowed_url(location):
                continue
            if tag == "sitemapindex":
                marker = source.get("sitemap_path_filter")
                if not marker or marker in urlsplit(location).path:
                    pending.append((location, depth + 1))
            else:
                found.append(location)
    return found


def product_url(url, client, source):
    parts = urlsplit(url)
    if source["id"] == "naheed":
        return client.allowed_url(url) and parts.path.strip("/").count("/") == 0 and parts.path != "/"
    return client.allowed_url(url) and any(marker in parts.path for marker in source.get("product_paths", []))


def collect_pages(client, source, db, emit, report):
    discovered = set()
    priced = 0

    def visit(url):
        nonlocal priced
        html = client.get(url)
        page = PageParser()
        page.feed(html)
        for href in page.links:
            candidate = urljoin(url, unescape(href))
            parts = urlsplit(candidate)
            candidate = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            if product_url(candidate, client, source):
                discovered.add(candidate)
        count = 0
        for item in parse_page(html, url, source["id"]):
            emit(item)
            count += 1
            priced += item.get("price_paisa") is not None
        return count

    for url in source.get("start_urls", []):
        visit(url)
    if source["adapter"] == "location_probe":
        report["coverage"] = "location_required"
        report["message"] = source["location_note"]
        return

    discovered.update(url for url in sitemap_urls(client, source, report) if product_url(url, client, source))
    urls = sorted(discovered)
    report["discovered_urls"] = len(urls)
    offset = int(checkpoint(db, source["id"], "page_offset") or "0")
    if urls:
        offset %= len(urls)
    visited = 0
    consecutive_errors = 0
    for index in range(len(urls)):
        position = (offset + index) % len(urls)
        if client.pages >= client.max_pages:
            report["coverage"] = "partial_rotating_batch"
            break
        try:
            visit(urls[position])
            consecutive_errors = 0
        except BudgetReached:
            report["coverage"] = "partial_rotating_batch"
            break
        except FetchError as error:
            report["errors"].append(str(error)[:400])
            consecutive_errors += 1
            if consecutive_errors >= 3:
                report["coverage"] = "source_errors_retry_next_cycle"
                break
        visited += 1
        checkpoint(db, source["id"], "page_offset", (position + 1) % len(urls))
    if not urls:
        report["coverage"] = "no_product_urls"
    elif visited == len(urls):
        report["coverage"] = "all_discovered_urls_visited"
    report["priced_records_seen"] = priced
