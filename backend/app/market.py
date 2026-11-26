"""Read-only access to the collector dataset. Planner seed prices remain separate."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/market", tags=["Retailer catalog"])


def database():
    root = Path(os.getenv("CATALOG_DIR", str(Path(__file__).resolve().parents[2] / "data" / "catalog")))
    path = root / "catalog.sqlite3"
    if not path.is_file():
        raise HTTPException(503, detail={"code": "catalog_unavailable", "message": "The grocery collector has not produced a dataset yet."})
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        return db
    except sqlite3.Error as error:
        raise HTTPException(503, detail={"code": "catalog_unavailable", "message": "The grocery dataset is not available."}) from error


def freshness(record):
    stamp = datetime.fromisoformat(record["observed_at"])
    age = max(0, (datetime.now(timezone.utc) - stamp).total_seconds() / 3600)
    return record | {"age_hours": round(age, 2), "stale": age > 36}


@router.get("/products")
def products(q: str = Query("", max_length=150), source: str | None = None,
             city: str | None = None, store_id: str | None = None,
             area: str | None = None, priced_only: bool = False,
             limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    conditions, parameters = [], []
    if q:
        literal = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append("(name LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\')")
        parameters.extend([f"%{literal}%", f"%{literal}%"])
    if source:
        conditions.append("source=?")
        parameters.append(source)
    if city:
        conditions.append("city=? COLLATE NOCASE")
        parameters.append(city)
    if store_id:
        conditions.append("json_extract(record,'$.location.store_id')=?")
        parameters.append(store_id)
    if area:
        conditions.append("json_extract(record,'$.location.delivery_area')=? COLLATE NOCASE")
        parameters.append(area)
    if priced_only:
        conditions.append("price_paisa IS NOT NULL")
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    db = database()
    try:
        total = db.execute("SELECT COUNT(*) FROM products" + where, parameters).fetchone()[0]
        rows = db.execute("SELECT record FROM products" + where + " ORDER BY name,source,id LIMIT ? OFFSET ?",
                          parameters + [limit, offset])
        items = [freshness(json.loads(row["record"])) for row in rows]
        return {"total": total, "limit": limit, "offset": offset, "items": items}
    finally:
        db.close()


@router.get("/sources")
def sources():
    db = database()
    try:
        items = []
        for row in db.execute("SELECT * FROM sources ORDER BY id"):
            run = db.execute("SELECT * FROM runs WHERE source=? ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM products WHERE source=?", (row["id"],)).fetchone()[0]
            latest = dict(run) if run else None
            if latest:
                latest["coverage"] = json.loads(latest["coverage"]) if latest["coverage"] else None
            items.append({"id": row["id"], "name": row["name"], "products": count, "latest_run": latest})
        return items
    finally:
        db.close()


@router.get("/products/{product_id}/history")
def history(product_id: str, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    db = database()
    try:
        if not db.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise HTTPException(404, detail={"code": "product_not_found", "message": "Product not found."})
        rows = db.execute("SELECT record FROM observations WHERE product_id=? ORDER BY run_id DESC LIMIT ? OFFSET ?",
                          (product_id, limit, offset))
        return {"product_id": product_id, "items": [json.loads(row["record"]) for row in rows],
                "limit": limit, "offset": offset}
    finally:
        db.close()


@router.get("/locations")
def locations(source: str | None = None):
    db = database()
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='collection_locations'").fetchone():
            return []
        sql = "SELECT * FROM collection_locations"
        parameters = []
        if source:
            sql += " WHERE source=?"
            parameters.append(source)
        items = []
        for row in db.execute(sql + " ORDER BY source,area", parameters):
            item = dict(row)
            item["details"] = json.loads(item["details"])
            item["products_in_database"] = db.execute(
                "SELECT count(*) FROM products WHERE source=? AND location_key=?",
                (item["source"], item["store_id"] + ":" + item["target_id"]),
            ).fetchone()[0]
            items.append(item)
        return items
    finally:
        db.close()
