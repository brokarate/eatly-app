"""Run with python -m bot.collect. All runtime artifacts stay under data/catalog."""
import argparse
import fcntl
import json
import logging
import os
import signal
import threading
import time
from pathlib import Path

from .adapters import collect_pages, collect_shopify
from .pandamart import collect as collect_pandamart
from .http import BudgetReached, Client, FetchError
from .store import atomic_file, begin_run, connect, export, initialize, now, save

ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger("meal.catalog")


def validate_record(record):
    if not str(record.get("external_id", "")).strip() or not str(record.get("name", "")).strip():
        raise ValueError("Missing product identifier or name")
    price = record.get("price_paisa")
    if price is not None and (not isinstance(price, int) or isinstance(price, bool) or price < 0):
        raise ValueError("Invalid integer price")
    if price is not None and record.get("currency") != "PKR":
        raise ValueError("A PKR price requires source currency PKR")
    for key in ("url", "image_url"):
        value = record.get(key)
        if value and (not isinstance(value, str) or not value.startswith("https://")):
            if key == "url":
                raise ValueError("Product URL must use HTTPS")
            record[key] = None


def run_source(db, root, source, max_pages):
    run_id = begin_run(db, source)
    client = Client(source.copy(), root, max_pages)
    seen = set()
    rejected = 0
    report = {"coverage": "unknown", "errors": []}

    def emit(record):
        nonlocal rejected
        try:
            validate_record(record)
        except (ValueError, TypeError):
            rejected += 1
            return
        key = save(db, run_id, source, record, client.last_evidence)
        seen.add(key)
        db.commit()

    status = "success"
    try:
        if source["adapter"] == "pandamart":
            collect_pandamart(client, source, db, emit, report, run_id)
        elif source["adapter"] == "shopify":
            collect_shopify(client, source, db, emit, report)
        else:
            collect_pages(client, source, db, emit, report)
        if report["coverage"] == "location_required":
            status = "location_required"
        elif not seen:
            status = "unavailable"
        elif report["errors"] or report["coverage"] in ("partial_rotating_batch", "store_catalog_batches"):
            status = "partial"
    except BudgetReached as error:
        status = "partial" if seen else "unavailable"
        report["coverage"] = "page_limit_reached"
        report["errors"].append(str(error))
    except (FetchError, ValueError, KeyError, TypeError) as error:
        status = "partial" if seen else "error"
        report["errors"].append(f"{type(error).__name__}: {error}")
    except Exception:
        LOGGER.exception("Unexpected source parser failure for %s", source["id"])
        status = "partial" if seen else "error"
        report["errors"].append("Unexpected parser failure. See worker log.")
    report.pop("previous_page", None)
    report["errors"] = report["errors"][:30]
    report["message"] = report.get("message") or "; ".join(report["errors"]) or "Public catalog processed"
    if status == "partial" and not report["errors"] and not report.get("message"):
        report["message"] = "Collected a rotating batch; additional discovered URLs remain"
    db.execute("""
        UPDATE runs SET finished_at=?,status=?,pages=?,records=?,rejected=?,message=?,coverage=? WHERE id=?
    """, (now(), status, client.pages, len(seen), rejected, report["message"], json.dumps(report), run_id))
    db.commit()
    result = {"source": source["id"], "run_id": run_id, "status": status,
              "pages": client.pages, "records": len(seen), "rejected": rejected, **report}
    LOGGER.info("%s", json.dumps(result, ensure_ascii=False))
    return result


def collect(args):
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another catalog collection is already running")
        sources = json.loads(Path(args.config).read_text())
        selected = set(args.sources.split(",")) if args.sources else {item["id"] for item in sources}
        unknown = selected - {item["id"] for item in sources}
        if unknown:
            raise SystemExit(f"Unknown sources: {sorted(unknown)}")
        with connect(root / "catalog.sqlite3") as db:
            initialize(db)
            results = []
            for item in sources:
                if item["id"] not in selected:
                    continue
                if args.shopify_sitemap_only and item["adapter"] == "shopify":
                    item = item | {"sitemap_only": True}
                results.append(run_source(db, root, item, args.max_pages))
                export(db, root)
                with atomic_file(root / "last-run.json") as output:
                    json.dump({"updated_at": now(), "sources": results}, output, indent=2)
        return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "bot" / "sources.json"))
    parser.add_argument("--output", default=os.getenv("CATALOG_DIR", str(ROOT / "data" / "catalog")))
    parser.add_argument("--sources", help="Comma-separated IDs. Default is every configured source.")
    parser.add_argument("--max-pages", type=int, default=1000,
                        help="Maximum requests per retailer per cycle, excluding robots. Default 1000.")
    parser.add_argument("--shopify-sitemap-only", action="store_true",
                        help="Recover missing Shopify products without repeating the bulk feed first.")
    parser.add_argument("--watch", action="store_true", help="Repeat collection every interval.")
    parser.add_argument("--interval-hours", type=float, default=24)
    args = parser.parse_args()
    if args.max_pages < 1 or args.interval_hours <= 0:
        parser.error("Page limit and interval must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = threading.Event()
    def shutdown(*_):
        stop.set()
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    while not stop.is_set():
        start = time.monotonic()
        try:
            collect(args)
            if not args.watch:
                break
            stop.wait(max(1, args.interval_hours * 3600 - (time.monotonic() - start)))
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
