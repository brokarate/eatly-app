import json
import tempfile
import unittest
from pathlib import Path

from bot.http import FetchError
from bot.pandamart import records, category_urls, inspect_store
from bot.store import connect, initialize, begin_run, save, export


def target(code="lxyu", area="Johar Town", key="johar-town"):
    return {"id": key, "area": area, "city": "Lahore", "store_id": code,
            "expected_name": "Pandamart " + area,
            "url": f"https://www.foodpanda.pk/darkstore/{code}/pandamart-store"}


def page(code="lxyu", price=99, city="Lahore"):
    state = {"initialState": {
        "VendorData:test": {"__typename": "VendorData", "code": code, "name": "Actual store name",
                            "location": {"city": {"name": city}, "latitude": 31.5, "longitude": 74.3},
                            "availability": {"status": "OPEN"}},
        "GroceryProductData:1": {"__typename": "GroceryProductData", "id": "1", "name": "Tomato 500g",
                                "vendorCode": code, "price": price, "originalPrice": 120,
                                "isAvailable": True, "urls": []},
        "GroceryProductData:other": {"__typename": "GroceryProductData", "id": "2", "name": "Wrong store product",
                                    "vendorCode": "karachi", "price": 10},
    }}
    return '<script>window.__PROVIDER_PROPS__=Object.assign(window.__PROVIDER_PROPS__||{},{apollo:' + json.dumps(state) + '});</script>'


class PandamartTests(unittest.TestCase):
    def test_product_has_verified_store_and_separate_area_context(self):
        listing = target()
        items = list(records(page(), listing, listing["url"]))
        self.assertEqual(len(items), 1)
        row = items[0]
        self.assertEqual(row["price_paisa"], 9900)
        self.assertEqual(row["location"]["store_id"], "lxyu")
        self.assertEqual(row["location"]["branch"], "Actual store name")
        self.assertEqual(row["location"]["delivery_area"], "Johar Town")
        self.assertFalse(row["location"]["delivery_confirmed"])
        self.assertEqual(row["package"]["quantity"], 500)

    def test_wrong_store_city_and_missing_identity_reject_all_prices(self):
        for html in (page("wrong"), page(city="Karachi"), "<html>Choose your location</html>"):
            with self.assertRaises(FetchError):
                list(records(html, target(), target()["url"]))

    def test_only_current_store_categories_are_discovered(self):
        html = page() + (
            '<a href="/darkstore/lxyu/pandamart-store/category/vegetables">Veg</a>'
            '<a href="/darkstore/other/other/category/vegetables">Other</a>'
        )
        parsed, _, _ = inspect_store(html, target())
        self.assertEqual(category_urls(parsed, target()), [
            target()["url"] + "/category/vegetables"
        ])

    def test_same_product_different_stores_and_delivery_targets_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = connect(root / "catalog.sqlite3")
            initialize(db)
            source = {"id": "pandamart", "name": "pandamart", "country": "PK", "location_note": "Public store catalogs"}
            run = begin_run(db, source)
            targets = [target(), target("gu85", "DHA Phase 5", "dha-phase-5"),
                       target("lxyu", "Another delivery area", "another-area")]
            keys = []
            for index, listing in enumerate(targets):
                row = next(records(page(listing["store_id"], price=99 + index), listing, listing["url"]))
                keys.append(save(db, run, source, row, {}))
            db.commit()
            self.assertEqual(len(set(keys)), 3)
            self.assertEqual(db.execute("SELECT count(*) FROM products").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT count(*) FROM observations").fetchone()[0], 3)
            export(db, root)
            self.assertIn("delivery_area", (root / "products.csv").read_text().splitlines()[0])
            db.close()


if __name__ == "__main__":
    unittest.main()
