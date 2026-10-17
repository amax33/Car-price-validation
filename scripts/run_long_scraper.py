"""Resumable, rate-limited collector for long public listing snapshots.

The collector intentionally stays on public index/detail pages. It does not log in,
solve CAPTCHAs, rotate identities, use proxies, or evade source controls.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import signal
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

import pandas as pd

from car_market.cleaning import clean_listings
from car_market.scrapers import JsonLdVehicleScraper, PublicIndexScraper
from car_market.storage import (
    ObservationStats,
    finish_crawl_run,
    load_listings,
    save_observations,
    start_crawl_run,
)


USER_AGENT = "NarinResearchBot/0.2 (public pages only)"
DIVAR_CITIES = {
    "tehran": "Tehran",
    "karaj": "Karaj",
    "mashhad": "Mashhad",
    "isfahan": "Isfahan",
    "shiraz": "Shiraz",
    "tabriz": "Tabriz",
    "qom": "Qom",
    "ahvaz": "Ahvaz",
    "rasht": "Rasht",
    "kermanshah": "Kermanshah",
    "urmia": "Urmia",
    "yazd": "Yazd",
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=8.0, help="Runtime; 0 means until Ctrl+C")
    parser.add_argument("--cycle-minutes", type=float, default=15.0)
    parser.add_argument("--delay", type=float, default=3.0, help="Minimum delay between requests")
    parser.add_argument("--cities", default=",".join(DIVAR_CITIES), help="Comma-separated Divar slugs")
    parser.add_argument("--bama-details", type=int, default=24, help="Maximum Bama details per cycle")
    parser.add_argument("--max-cycles", type=int, default=0, help="Optional safety cap; 0 is unlimited")
    parser.add_argument("--max-db-mb", type=float, default=1024.0)
    parser.add_argument("--database", type=Path, default=Path("data/real_market.db"))
    parser.add_argument("--latest-raw", type=Path, default=Path("data/raw/latest_real_snapshot.csv"))
    parser.add_argument("--cumulative-raw", type=Path, default=Path("data/raw/real_listings.csv"))
    parser.add_argument("--clean-output", type=Path, default=Path("data/processed/real_listings.csv"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("data/raw/snapshots"))
    parser.add_argument("--state", type=Path, default=Path("data/raw/long_scraper_state.json"))
    parser.add_argument("--log", type=Path, default=Path("data/raw/long_scraper.log"))
    parser.add_argument("--no-snapshot-files", action="store_true")
    args = parser.parse_args()
    if args.hours < 0 or args.cycle_minutes < 5 or args.delay < 1:
        parser.error("hours must be >= 0, cycle-minutes >= 5, and delay >= 1 second")
    if not 0 <= args.bama_details <= 100:
        parser.error("bama-details must be between 0 and 100")
    requested = [part.strip().casefold() for part in args.cities.split(",") if part.strip()]
    unknown = sorted(set(requested) - set(DIVAR_CITIES))
    if unknown:
        parser.error(f"unknown city slugs: {', '.join(unknown)}")
    if not requested:
        parser.error("at least one Divar city is required")
    args.cities = requested
    return args


def setup_logging(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("long_scraper")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.StreamHandler(), logging.FileHandler(path, encoding="utf-8")):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def robots_allows(url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    request = Request(robots_url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:  # noqa: S310 - known source robots URL
        content = response.read().decode("utf-8", "replace")
    parser = RobotFileParser(robots_url)
    parser.parse(content.splitlines())
    return parser.can_fetch(USER_AGENT, url)


def acquire_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError("another long scraper is already using this database") from exc
    handle.write(str(__import__("os").getpid()))
    handle.flush()
    return handle


def collect_cycle(args: argparse.Namespace, stop: threading.Event, logger: logging.Logger) -> dict:
    config = {
        "cities": args.cities,
        "delay_seconds": args.delay,
        "bama_details": args.bama_details,
        "user_agent": USER_AGENT,
    }
    run_id = start_crawl_run(args.database, config)
    observed_at = iso_now()
    rows: list[dict] = []
    errors: list[tuple[str, str]] = []
    scope_counts: dict[str, int] = {}
    status = "complete"
    try:
        for slug in args.cities:
            if stop.is_set():
                status = "interrupted"
                break
            scope = f"divar_{slug}"
            result = JsonLdVehicleScraper(
                [f"https://divar.ir/s/{slug}/car"], "divar", args.delay, "irr"
            ).collect()
            for row in result.rows:
                if row.get("city") == "unknown":
                    row["city"] = DIVAR_CITIES[slug]
                row["crawl_scope"] = scope
                row["observed_at"] = observed_at
            rows.extend(result.rows)
            errors.extend((scope, error) for error in result.errors)
            scope_counts[scope] = len(result.rows)
            logger.info("run=%s scope=%s rows=%s errors=%s", run_id, scope, len(result.rows), len(result.errors))
            stop.wait(args.delay)

        if not stop.is_set() and args.bama_details:
            scope = "bama_index"
            result = PublicIndexScraper(
                "https://bama.ir/car",
                "bama",
                "/car/detail-",
                max_details=args.bama_details,
                delay_seconds=args.delay,
                price_unit="toman",
            ).collect()
            for row in result.rows:
                row["crawl_scope"] = scope
                row["observed_at"] = observed_at
            rows.extend(result.rows)
            errors.extend((scope, error) for error in result.errors)
            scope_counts[scope] = len(result.rows)
            logger.info("run=%s scope=%s rows=%s errors=%s", run_id, scope, len(result.rows), len(result.errors))

        raw = pd.DataFrame(rows)
        if raw.empty:
            clean = raw
            stats = ObservationStats(0, 0, 0)
            status = "empty" if status == "complete" else status
        else:
            raw = raw.drop_duplicates(["source", "source_listing_id"], keep="last")
            clean, _ = clean_listings(raw)
            stats = save_observations(clean, args.database, run_id, observed_at)
            atomic_csv(args.latest_raw, raw)
            if not args.no_snapshot_files:
                stamp = observed_at.replace(":", "-").replace("+", "_")
                atomic_csv(args.snapshot_dir / f"run_{run_id}_{stamp}.csv", raw)
            if args.cumulative_raw.exists():
                previous = pd.read_csv(args.cumulative_raw)
                raw = pd.concat([previous, raw], ignore_index=True)
                raw = raw.drop_duplicates(["source", "source_listing_id"], keep="last")
            atomic_csv(args.cumulative_raw, raw)
            atomic_csv(args.clean_output, load_listings(args.database))
        finish_crawl_run(args.database, run_id, status, len(rows), len(clean), stats, errors)
    except Exception as exc:
        status = "failed"
        errors.append(("runner", f"{type(exc).__name__}: {exc}"))
        finish_crawl_run(args.database, run_id, status, len(rows), 0, ObservationStats(0, 0, 0), errors)
        logger.exception("run=%s failed", run_id)

    result = {
        "run_id": run_id,
        "finished_at": iso_now(),
        "status": status,
        "scope_counts": scope_counts,
        "raw_rows": len(rows),
        "clean_rows": int(len(clean)) if "clean" in locals() else 0,
        "new_listings": stats.new if "stats" in locals() else 0,
        "changed_listings": stats.changed if "stats" in locals() else 0,
        "errors": [{"scope": scope, "error": error} for scope, error in errors],
    }
    logger.info("cycle summary %s", json.dumps(result, ensure_ascii=False))
    return result


def database_summary(path: Path) -> dict:
    with sqlite3.connect(path) as connection:
        return {
            "unique_listings": connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0],
            "observations": connection.execute("SELECT COUNT(*) FROM listing_observations").fetchone()[0],
            "crawl_runs": connection.execute("SELECT COUNT(*) FROM crawl_runs").fetchone()[0],
            "database_mb": round(path.stat().st_size / 1_048_576, 3),
        }


def main() -> int:
    args = parse_arguments()
    logger = setup_logging(args.log)
    stop = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stop.set())
    try:
        lock = acquire_lock(args.database.with_suffix(args.database.suffix + ".lock"))
    except RuntimeError as exc:
        logger.error(str(exc))
        return 2

    try:
        checks = [f"https://divar.ir/s/{args.cities[0]}/car", "https://bama.ir/car"]
        for url in checks:
            if not robots_allows(url):
                logger.error("robots.txt does not allow %s; stopping", url)
                return 3
        deadline = utc_now() + timedelta(hours=args.hours) if args.hours else None
        cycle = 0
        failure_backoff = 1.0
        last_result: dict = {}
        while not stop.is_set():
            if deadline and utc_now() >= deadline:
                break
            if args.max_cycles and cycle >= args.max_cycles:
                break
            if args.database.exists() and args.database.stat().st_size > args.max_db_mb * 1_048_576:
                logger.warning("database size limit reached; stopping")
                break
            cycle += 1
            last_result = collect_cycle(args, stop, logger)
            attempted = max(len(last_result.get("scope_counts", {})), 1)
            failed_scopes = len({item["scope"] for item in last_result.get("errors", [])})
            if last_result["status"] in {"failed", "empty"} or failed_scopes / attempted >= 0.5:
                failure_backoff = min(failure_backoff * 2, 4.0)
            else:
                failure_backoff = 1.0
            summary = database_summary(args.database)
            atomic_json(args.state, {
                "updated_at": iso_now(),
                "cycle": cycle,
                "next_delay_minutes": args.cycle_minutes * failure_backoff,
                "last_run": last_result,
                **summary,
            })
            if args.max_cycles and cycle >= args.max_cycles:
                break
            wait_seconds = args.cycle_minutes * 60 * failure_backoff
            if deadline:
                wait_seconds = min(wait_seconds, max((deadline - utc_now()).total_seconds(), 0))
            if wait_seconds > 0 and not stop.is_set():
                logger.info("waiting %.1f minutes before next cycle", wait_seconds / 60)
                stop.wait(wait_seconds)
        logger.info("stopped cleanly: %s", database_summary(args.database))
        return 0
    finally:
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
