import json
import tempfile
import unittest
from pathlib import Path

from bot.adapters import PageParser, parse_page, shopify_records
from bot.collect import run_source
from bot.http import Client, FetchError, bounded_request
from bot.normalize import nutrition, package_size, price_paisa
from bot.store import begin_run, connect, export, initialize, save
from unittest.mock import MagicMock, patch


class NormalizationTests(unittest.TestCase):
    def test_prices_are_integer_paisa(self):
        self.assertEqual(price_paisa("Rs. 1,295.50"), 129550)
        self.assertEqual(price_paisa("0"), 0)
        for value in ("Rs. 120 - 240", None, "NaN", "-2", "1.234", "Infinity"):
            self.assertIsNone(price_paisa(value))

    def test_advertised_packages_and_ranges(self):
        self.assertEqual(package_size("Rice 2 x 1 KG")["quantity"], 2000)
        self.assertEqual(package_size("500 GM")["unit"], "g")
        self.assertEqual(package_size("Oil 1.5 L")["quantity"], 1500)
        self.assertEqual(package_size("Eggs 12 PCS")["quantity"], 12)
        self.assertIsNone(package_size("Tomato (1 KG TO 250 GM)"))
        self.assertIsNone(package_size("Small bag"))
        self.assertIsNone(package_size("1/2 kg"))
        self.assertIsNone(package_size("500+100 g"))
        self.assertIsNone(package_size("Rice 1kg 2kg"))

    def test_nutrition_keeps_basis_and_does_not_infer_macros(self):
        value = nutrition({"servingSize": "100 g", "calories": "250 kcal", "proteinContent": "8 g"})
        self.assertEqual(value["basis"], "100 g")
        self.assertEqual(value["macros"]["protein"], {"value": 8.0, "unit": "g"})
        self.assertEqual(nutrition("Rich in protein")["macros"], {})
        self.assertIsNone(nutrition(None))
        label = nutrition("Nutrition per 100 g: Energy 220 kcal Protein 8 g Total Fat 3 g")
        self.assertEqual(label["basis"], "100 g")
        self.assertEqual(label["macros"]["protein"]["value"], 8)
        self.assertIsNone(nutrition({"proteinContent": "8 g"})["basis"])

    def test_shopify_variants_keep_distinct_sizes_and_zero_price(self):
        document = {"products": [{
            "id": 1, "title": "Tomato (1 KG TO 250 GM)", "handle": "tomato", "vendor": "Store",
            "body_html": "<p>Fresh tomatoes</p>", "variants": [
                {"id": 11, "title": "250 GM", "price": "39.50", "available": True},
                {"id": 12, "title": "1 KG", "price": "0", "available": False},
            ],
        }]}
        rows = list(shopify_records(document, "https://example.com"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["price_paisa"], 3950)
        self.assertEqual(rows[0]["package"]["quantity"], 250)
        self.assertEqual(rows[1]["price_paisa"], 0)
        self.assertFalse(rows[1]["available"])
        self.assertIsNone(rows[0]["nutrition"])

    def test_jsonld_products_do_not_confuse_aggregate_or_foreign_prices(self):
        product = {"@type": "Product", "name": "Rice 1kg", "sku": "rice",
                   "offers": {"@type": "Offer", "price": "319.00", "priceCurrency": "PKR",
                              "availability": "https://schema.org/InStock"},
                   "nutrition": {"servingSize": "30 g", "fatContent": "2 g"}}
        html = '<script type="application/ld+json">' + json.dumps({"@graph": [product]}) + "</script>"
        row = list(parse_page(html, "https://example.com/product/rice", "imtiaz"))[0]
        self.assertEqual(row["price_paisa"], 31900)
        self.assertTrue(row["available"])
        self.assertEqual(row["nutrition"]["basis"], "30 g")
        product["offers"] = {"@type": "AggregateOffer", "lowPrice": "10", "highPrice": "50", "priceCurrency": "PKR"}
        html = '<script type="application/ld+json">' + json.dumps(product) + "</script>"
        self.assertIsNone(list(parse_page(html, "https://example.com/p", "x"))[0]["price_paisa"])

    def test_metro_flight_preserves_store_and_effective_price(self):
        raw = {"store_variant_id": 10, "store_id": 2, "store_name": "Canal", "store_city_name": "Lahore",
               "variant_id": 4, "product_name": "Lentils", "variant_weight": 0.5, "variant_unit_type": "KG",
               "effective_price": 189, "sale_price": 999, "is_in_stock": True}
        payload = "a:" + json.dumps({"products": [raw]})
        split = len(payload) // 2
        html = "".join("<script>self.__next_f.push(" + json.dumps([1, chunk]) + ")</script>"
                       for chunk in [payload[:split], payload[split:]])
        row = list(parse_page(html, "https://www.metro-online.pk/home", "metro"))[0]
        self.assertEqual(row["price_paisa"], 18900)
        self.assertEqual(row["package"]["quantity"], 500)
        self.assertEqual(row["location"]["city"], "Lahore")
        self.assertEqual(row["location"]["store_id"], "2")


class NetworkTests(unittest.TestCase):
    def test_request_timeout_terminates_network_process(self):
        context = MagicMock()
        receiver, sender = MagicMock(), MagicMock()
        context.Pipe.return_value = (receiver, sender)
        receiver.poll.return_value = False
        process = context.Process.return_value
        process.is_alive.side_effect = [True, False]
        with patch("bot.http.multiprocessing.get_context", return_value=context):
            with self.assertRaises(TimeoutError):
                bounded_request("https://example.com", {"example.com"}, timeout=0.01)
        process.terminate.assert_called_once()
        receiver.close.assert_called_once()

    def test_rate_limit_backoff_survives_worker_restart(self):
        source = {"id": "test", "hosts": ["example.com"], "delay_seconds": 0}
        with tempfile.TemporaryDirectory() as directory:
            with patch("bot.http.bounded_request", return_value=("http_error", 429, "86400")) as request:
                with self.assertRaisesRegex(FetchError, "backoff saved"):
                    Client(source, Path(directory), 5)._raw("https://example.com/products")
                with self.assertRaisesRegex(FetchError, "saved rate-limit pause"):
                    Client(source, Path(directory), 5)._raw("https://example.com/products")
                request.assert_called_once()

    def test_rate_limit_http_date_is_respected(self):
        source = {"id": "test", "hosts": ["example.com"], "delay_seconds": 0}
        with tempfile.TemporaryDirectory() as directory:
            with patch("bot.http.time.time", return_value=0), patch(
                    "bot.http.bounded_request", return_value=("http_error", 429, "Thu, 01 Jan 1970 01:00:00 GMT")):
                with self.assertRaises(FetchError):
                    Client(source, Path(directory), 5)._raw("https://example.com/products")
            value = json.loads((Path(directory) / "cooldowns" / "test.json").read_text())
            self.assertEqual(value["retry_at"], 3600)

    def test_forbidden_response_stops_without_bypassing(self):
        source = {"id": "test", "hosts": ["example.com"], "delay_seconds": 0}
        with tempfile.TemporaryDirectory() as directory:
            client = Client(source, Path(directory), 5)
            with patch("bot.http.bounded_request", return_value=("http_error", 403, "")) as request:
                with self.assertRaisesRegex(FetchError, "HTTP 403"):
                    client._raw("https://example.com/products")
                request.assert_called_once()
            self.assertFalse(client.allowed_url("https://elsewhere.com/products"))
            self.assertFalse(client.allowed_url("http://example.com/products"))



class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db = connect(self.root / "catalog.sqlite3")
        initialize(self.db)
        self.source = {"id": "test", "name": "Test", "country": "PK", "adapter": "shopify",
                       "base_url": "https://example.com", "hosts": ["example.com"], "location_note": "Unspecified"}

    def tearDown(self):
        self.db.close()
        self.temporary.cleanup()

    def test_history_upserts_and_export(self):
        record = {"external_id": "1", "name": "Rice", "currency": "PKR", "price_paisa": 10000,
                  "url": "https://example.com/rice", "package": None}
        first = begin_run(self.db, self.source)
        key = save(self.db, first, self.source, record, {"sha256": "abc"})
        save(self.db, first, self.source, record, {"sha256": "abc"})
        second = begin_run(self.db, self.source)
        save(self.db, second, self.source, record | {"price_paisa": 12000}, {})
        self.db.commit()
        self.assertEqual(self.db.execute("SELECT count(*) FROM products").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM observations").fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT price_paisa FROM products").fetchone()[0], 12000)
        saved = json.loads(self.db.execute("SELECT record FROM products WHERE id=?", (key,)).fetchone()[0])
        self.assertIsNone(saved["location"]["city"])
        self.assertFalse(saved["is_sample"])
        export(self.db, self.root)
        self.assertEqual(len((self.root / "products.jsonl").read_text().splitlines()), 1)
        self.assertTrue((self.root / "products.csv").is_file())

    def test_failed_source_does_not_delete_last_known_prices(self):
        run_id = begin_run(self.db, self.source)
        save(self.db, run_id, self.source, {"external_id": "1", "name": "Rice", "price_paisa": 100, "currency": "PKR"}, {})
        self.db.commit()
        with patch.object(Client, "get_json", side_effect=FetchError("HTTP 403")):
            result = run_source(self.db, self.root, self.source, 10)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.db.execute("SELECT count(*) FROM products").fetchone()[0], 1)

    def test_partial_run_retains_successful_pages(self):
        document = {"products": [{"id": 1, "title": "Rice 1kg", "handle": "rice",
                                 "variants": [{"id": 1, "price": "100", "title": "1 KG"}]}]}
        with patch.object(Client, "get_json", side_effect=[document, FetchError("HTTP 429")]):
            result = run_source(self.db, self.root, self.source, 10)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["records"], 1)


if __name__ == "__main__":
    unittest.main()
