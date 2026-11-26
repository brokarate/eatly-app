import csv
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_key(source, external_id, location_key):
    return hashlib.sha256(f"{source}\n{external_id}\n{location_key}".encode()).hexdigest()


def connect(path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, config TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY, source TEXT NOT NULL REFERENCES sources(id),
            started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
            pages INTEGER NOT NULL DEFAULT 0, records INTEGER NOT NULL DEFAULT 0,
            rejected INTEGER NOT NULL DEFAULT 0, message TEXT, coverage TEXT
        );
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL,
            name TEXT NOT NULL, category TEXT, city TEXT, location_key TEXT NOT NULL,
            price_paisa INTEGER, observed_at TEXT NOT NULL, run_id INTEGER NOT NULL REFERENCES runs(id),
            record TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS products_source ON products(source);
        CREATE INDEX IF NOT EXISTS products_city ON products(city);
        CREATE TABLE IF NOT EXISTS observations (
            product_id TEXT NOT NULL REFERENCES products(id),
            run_id INTEGER NOT NULL REFERENCES runs(id), observed_at TEXT NOT NULL,
            price_paisa INTEGER, record TEXT NOT NULL,
            PRIMARY KEY(product_id, run_id)
        );
        CREATE TABLE IF NOT EXISTS collection_locations (
            source TEXT NOT NULL, target_id TEXT NOT NULL, area TEXT NOT NULL,
            city TEXT NOT NULL, store_id TEXT, branch TEXT, url TEXT NOT NULL,
            status TEXT NOT NULL, checked_at TEXT NOT NULL, run_id INTEGER REFERENCES runs(id),
            records INTEGER NOT NULL DEFAULT 0, error TEXT, details TEXT NOT NULL,
            PRIMARY KEY(source,target_id)
        );
        CREATE TABLE IF NOT EXISTS checkpoints (
            source TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY(source, name)
        );
    """)
    # A crashed worker must never leave a run appearing healthy.
    db.execute("UPDATE runs SET status='interrupted', finished_at=? WHERE status='running'", (now(),))
    db.commit()


def begin_run(db, source):
    db.execute("INSERT INTO sources VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, config=excluded.config",
               (source["id"], source["name"], json.dumps(source)))
    cursor = db.execute("INSERT INTO runs(source, started_at, status) VALUES(?,?,'running')", (source["id"], now()))
    db.commit()
    return cursor.lastrowid


def save(db, run_id, source, record, evidence):
    external_id = str(record["external_id"])
    location = record.get("location") or {}
    location_key = str(location.get("store_id") or location.get("branch") or "public-unspecified")
    if source["id"] == "pandamart" and location.get("target_id"):
        location_key += ":" + location["target_id"]
    key = record_key(source["id"], external_id, location_key)
    stamp = now()
    record = record | {
        "id": key, "source": source["id"], "retailer": source["name"],
        "currency": record.get("currency"),
        "country": source.get("country", "PK"), "observed_at": stamp,
        "location": {"city": None, "branch": None, "store_id": None,
                     "scope": "public_storefront_unspecified", "note": source["location_note"]} | location,
        "evidence": dict(evidence or {}), "is_sample": False,
    }
    if record["location"]["scope"] == "source_explicit":
        record["location"]["note"] = "Location is explicitly published in the source record."
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True)
    db.execute("""
        INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          name=excluded.name, category=excluded.category, city=excluded.city,
          price_paisa=excluded.price_paisa, observed_at=excluded.observed_at,
          run_id=excluded.run_id, record=excluded.record
    """, (key, source["id"], external_id, record["name"], record.get("category"),
          record["location"].get("city"), location_key, record.get("price_paisa"), stamp, run_id, encoded))
    db.execute("""
        INSERT INTO observations VALUES(?,?,?,?,?)
        ON CONFLICT(product_id,run_id) DO UPDATE SET
          observed_at=excluded.observed_at, price_paisa=excluded.price_paisa, record=excluded.record
    """, (key, run_id, stamp, record.get("price_paisa"), encoded))
    return key


def checkpoint(db, source, name, value=None):
    if value is None:
        row = db.execute("SELECT value FROM checkpoints WHERE source=? AND name=?", (source, name)).fetchone()
        return row["value"] if row else None
    db.execute("INSERT INTO checkpoints VALUES(?,?,?) ON CONFLICT(source,name) DO UPDATE SET value=excluded.value",
               (source, name, str(value)))
    db.commit()


@contextmanager
def atomic_file(path):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".export-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
            yield output
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def export(db, root):
    fields = ["id", "source", "retailer", "external_id", "name", "brand", "category", "currency",
              "price_paisa", "price_pkr", "package_quantity", "package_unit", "available",
              "city", "branch", "store_id", "location_scope", "delivery_area", "delivery_confirmed",
              "target_id", "observed_at", "url", "image_url", "nutrition"]
    with atomic_file(root / "products.jsonl") as jsonl, atomic_file(root / "products.csv") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        for row in db.execute("SELECT record FROM products ORDER BY source,id"):
            item = json.loads(row["record"])
            jsonl.write(json.dumps(item, ensure_ascii=False) + "\n")
            package, location = item.get("package") or {}, item["location"]
            flat = {field: item.get(field) for field in fields}
            flat.update(price_pkr=format(Decimal(item["price_paisa"]) / 100, ".2f") if item.get("price_paisa") is not None else None,
                        package_quantity=package.get("quantity"), package_unit=package.get("unit"),
                        city=location.get("city"), branch=location.get("branch"), store_id=location.get("store_id"),
                        location_scope=location["scope"], delivery_area=location.get("delivery_area"),
                        delivery_confirmed=location.get("delivery_confirmed"), target_id=location.get("target_id"),
                        nutrition=json.dumps(item.get("nutrition"), ensure_ascii=False))
            writer.writerow(flat)
