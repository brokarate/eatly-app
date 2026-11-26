import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.adapters import sitemap_urls
from bot.collect import run_source
from bot.http import BudgetReached, FetchError
from bot.store import connect, initialize

BASE = 'https://example.com'

def product(handle, number):
    return {'id': number, 'title': handle + ' 1kg', 'handle': handle,
            'tags': 'Food, Barcode_123',
            'variants': [{'id': number * 10, 'title': '1 KG', 'price': '149.50'}]}

def xml(kind, urls):
    entry = 'sitemap' if kind == 'sitemapindex' else 'url'
    return '<' + kind + '>' + ''.join(f'<{entry}><loc>{url}</loc></{entry}>' for url in urls) + '</' + kind + '>'

class FakeClient:
    def __init__(self, responses, budget=30):
        self.responses, self.max_pages = responses, budget
        self.pages, self.calls, self.last_evidence = 0, [], {}

    def allowed_url(self, url):
        return url.startswith(BASE + '/')

    def get(self, url):
        if self.pages >= self.max_pages:
            raise BudgetReached('budget')
        self.pages += 1
        self.calls.append(url)
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        return value

    def get_json(self, url):
        return self.get(url)

class ShopifyCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = connect(self.root / 'catalog.sqlite3')
        initialize(self.db)
        self.source = {'id': 'test', 'name': 'Test', 'adapter': 'shopify', 'country': 'PK',
                       'base_url': BASE, 'hosts': ['example.com'], 'location_note': 'Unknown',
                       'sitemaps': [BASE + '/sitemap.xml'], 'product_paths': ['/products/'],
                       'sitemap_path_filter': '/sitemap_products_', 'max_sitemaps': 256}
        self.responses = {
            BASE + '/products.json?limit=250&page=1': {'products': [product('rice', 1)]},
            BASE + '/sitemap.xml': xml('sitemapindex', [BASE + '/sitemap_products_1.xml', BASE + '/sitemap_collections_1.xml']),
            BASE + '/sitemap_products_1.xml': xml('urlset', [BASE + '/products/' + h for h in ('rice', 'lentils', 'oil')]),
            BASE + '/products/lentils.json': {'product': product('lentils', 2)},
            BASE + '/products/oil.json': {'product': product('oil', 3)},
        }

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def run_batch(self, budget=30):
        client = FakeClient(self.responses, budget)
        with patch('bot.collect.Client', return_value=client), patch('bot.adapters.SHOPIFY_MAX_FEED_PAGES', 1):
            result = run_source(self.db, self.root, self.source, budget)
        return result, client

    def test_sitemap_recovers_products_without_requesting_past_feed_limit(self):
        result, client = self.run_batch()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['records'], 3)
        self.assertEqual(result['missing_urls_after_batch'], 0)
        self.assertNotIn(BASE + '/products.json?limit=250&page=2', client.calls)
        self.assertNotIn(BASE + '/sitemap_collections_1.xml', client.calls)
        row = json.loads(self.db.execute("select record from products where external_id='20'").fetchone()[0])
        self.assertEqual(row['price_paisa'], 14950)
        self.assertEqual(row['barcode'], '123')
        self.assertEqual(row['tags'], ['Food', 'Barcode_123'])
        self.assertIsNone(row['available'])

    def test_budget_resumes_with_uncollected_products_first(self):
        first, _ = self.run_batch(4)
        self.assertEqual(first['status'], 'partial')
        self.assertEqual(first['missing_urls_after_batch'], 1)
        second, client = self.run_batch(4)
        self.assertEqual(second['missing_urls_after_batch'], 0)
        self.assertIn(BASE + '/products/oil.json', client.calls)
        self.assertNotIn(BASE + '/products/lentils.json', client.calls)
        self.assertEqual(self.db.execute('select count(*) from products').fetchone()[0], 3)

    def test_rate_limit_stops_batch_and_preserves_feed_prices(self):
        self.responses[BASE + '/products/lentils.json'] = FetchError('HTTP 429; retry postponed to next run')
        result, client = self.run_batch()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['missing_urls_after_batch'], 2)
        self.assertNotIn(BASE + '/products/oil.json', client.calls)
        self.assertEqual(self.db.execute('select count(*) from products').fetchone()[0], 1)

    def test_wrong_product_identity_is_not_saved(self):
        self.responses[BASE + '/products/lentils.json'] = {'product': product('foreign-product', 2)}
        result, _ = self.run_batch()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['missing_urls_after_batch'], 1)
        self.assertEqual(self.db.execute("select count(*) from products where external_id='20'").fetchone()[0], 0)

    def test_refresh_rotates_after_missing_products_are_saved(self):
        self.run_batch()
        _, first = self.run_batch(4)
        _, second = self.run_batch(4)
        self.assertIn(BASE + '/products/lentils.json', first.calls)
        self.assertIn(BASE + '/products/oil.json', second.calls)

    def test_sitemap_only_recovery_skips_bulk_feed(self):
        self.source['sitemap_only'] = True
        self.responses[BASE + '/products/rice.json'] = {'product': product('rice', 1)}
        result, client = self.run_batch()
        self.assertEqual(result['records'], 3)
        self.assertFalse(any('/products.json?' in url for url in client.calls))

    def test_product_discovery_supports_more_than_64_sitemaps(self):
        urls = [BASE + f'/sitemap_products_{i}.xml' for i in range(70)]
        responses = {BASE + '/sitemap.xml': xml('sitemapindex', urls)}
        responses.update({url: xml('urlset', [BASE + f'/products/item-{i}']) for i, url in enumerate(urls)})
        report = {'errors': []}
        discovered = sitemap_urls(FakeClient(responses, 100), self.source, report)
        self.assertEqual(len(discovered), 70)
        self.assertEqual(report['errors'], [])

if __name__ == '__main__':
    unittest.main()
