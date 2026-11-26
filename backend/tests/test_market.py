import json
import sqlite3

from fastapi.testclient import TestClient

from app.main import app


def test_market_reads_real_catalog_and_preserves_unknown_location(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DIR", str(tmp_path))
    client = TestClient(app)
    assert client.get("/market/products").status_code == 503
    db = sqlite3.connect(tmp_path / "catalog.sqlite3")
    db.executescript("""
        CREATE TABLE products(id TEXT, source TEXT, name TEXT, category TEXT, city TEXT,
                              price_paisa INTEGER, observed_at TEXT, record TEXT);
        CREATE TABLE observations(product_id TEXT, run_id INTEGER, record TEXT);
    """)
    record = {"id": "rice", "source": "test", "name": "Rice", "currency": "PKR", "price_paisa": 31900,
              "observed_at": "2020-01-01T00:00:00+00:00", "location": {"city": None}, "nutrition": None}
    db.execute("INSERT INTO products VALUES(?,?,?,?,?,?,?,?)",
               ("rice", "test", "Rice", "Grains", None, 31900, record["observed_at"], json.dumps(record)))
    db.execute("INSERT INTO observations VALUES(?,?,?)", ("rice", 1, json.dumps(record)))
    db.commit()
    response = client.get("/market/products", params={"q": "rice", "priced_only": True}).json()
    assert response["total"] == 1
    assert response["items"][0]["stale"] is True
    assert response["items"][0]["location"]["city"] is None
    assert client.get("/market/products", params={"city": "Lahore"}).json()["total"] == 0
    assert client.get("/market/products", params={"q": "%"}).json()["total"] == 0
    assert client.get("/market/products", params={"limit": 1000}).status_code == 422
    assert client.get("/market/products/rice/history").json()["items"] == [record]
    assert client.get("/market/products/missing/history").status_code == 404
    assert client.get("/market/locations").json() == []
    local = record | {"id": "panda-rice", "source": "pandamart", "location": {
        "city": "Lahore", "store_id": "lxyu", "delivery_area": "Johar Town",
        "delivery_confirmed": False}}
    db.execute("INSERT INTO products VALUES(?,?,?,?,?,?,?,?)",
               ("panda-rice", "pandamart", "Rice", "Grains", "Lahore", 31900,
                record["observed_at"], json.dumps(local)))
    db.commit()
    assert client.get("/market/products", params={"store_id": "lxyu", "area": "Johar Town"}).json()["total"] == 1
    assert client.get("/market/products", params={"store_id": "gu85", "area": "Johar Town"}).json()["total"] == 0
    assert client.get("/market/products", params={"store_id": "lxyu", "area": "DHA Phase 5"}).json()["total"] == 0
    db.close()
