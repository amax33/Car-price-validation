from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pandas as pd


SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_listing_id TEXT NOT NULL,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    trim TEXT NOT NULL,
    year INTEGER NOT NULL CHECK(year BETWEEN 1980 AND 2100),
    mileage_km INTEGER NOT NULL CHECK(mileage_km >= 0),
    body_condition TEXT NOT NULL,
    city TEXT NOT NULL,
    transmission TEXT NOT NULL,
    fuel_type TEXT NOT NULL,
    asking_price REAL NOT NULL CHECK(asking_price > 0),
    listing_date TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    seen_count INTEGER NOT NULL DEFAULT 1,
    UNIQUE(source, source_listing_id)
);
CREATE INDEX IF NOT EXISTS idx_vehicle ON listings(make, model, year);
CREATE INDEX IF NOT EXISTS idx_date ON listings(listing_date);
CREATE TABLE IF NOT EXISTS crawl_runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    config_json TEXT NOT NULL,
    raw_count INTEGER NOT NULL DEFAULT 0,
    clean_count INTEGER NOT NULL DEFAULT 0,
    new_count INTEGER NOT NULL DEFAULT 0,
    changed_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS listing_observations (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    crawl_run_id INTEGER NOT NULL REFERENCES crawl_runs(id),
    observed_at TEXT NOT NULL,
    scope TEXT NOT NULL,
    asking_price REAL NOT NULL,
    mileage_km INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE(listing_id, crawl_run_id)
);
CREATE INDEX IF NOT EXISTS idx_observation_listing ON listing_observations(listing_id, observed_at);
CREATE TABLE IF NOT EXISTS crawl_errors (
    id INTEGER PRIMARY KEY,
    crawl_run_id INTEGER NOT NULL REFERENCES crawl_runs(id),
    scope TEXT NOT NULL,
    error TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
"""

COLUMNS = [
    "source", "source_listing_id", "make", "model", "trim", "year", "mileage_km",
    "body_condition", "city", "transmission", "fuel_type", "asking_price", "listing_date", "url",
]


@dataclass(frozen=True)
class ObservationStats:
    seen: int
    new: int
    changed: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    existing = {row[1] for row in connection.execute("PRAGMA table_info(listings)")}
    migrations = {
        "first_seen_at": "TEXT",
        "last_seen_at": "TEXT",
        "seen_count": "INTEGER NOT NULL DEFAULT 1",
    }
    for name, definition in migrations.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE listings ADD COLUMN {name} {definition}")
    connection.execute(
        "UPDATE listings SET first_seen_at=COALESCE(first_seen_at, collected_at), "
        "last_seen_at=COALESCE(last_seen_at, collected_at), seen_count=COALESCE(seen_count, 1)"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_last_seen ON listings(last_seen_at)")


def save_listings(frame: pd.DataFrame, path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = frame.copy()
    rows["listing_date"] = rows["listing_date"].astype(str)
    if "url" not in rows:
        rows["url"] = ""
    else:
        rows["url"] = rows["url"].fillna("")
    values = list(rows[COLUMNS].itertuples(index=False, name=None))
    placeholders = ",".join("?" for _ in COLUMNS)
    updates = ",".join(f"{c}=excluded.{c}" for c in COLUMNS[2:])
    sql = f"INSERT INTO listings ({','.join(COLUMNS)}) VALUES ({placeholders}) ON CONFLICT(source, source_listing_id) DO UPDATE SET {updates}"
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        connection.executemany(sql, values)
        connection.commit()
    return len(values)


def load_listings(path: str | Path) -> pd.DataFrame:
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        return pd.read_sql_query("SELECT * FROM listings ORDER BY listing_date", connection)


def start_crawl_run(path: str | Path, config: dict) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        cursor = connection.execute(
            "INSERT INTO crawl_runs(started_at,status,config_json) VALUES(?,?,?)",
            (_utc_now(), "running", json.dumps(config, ensure_ascii=False, sort_keys=True)),
        )
        connection.commit()
        return int(cursor.lastrowid)


def finish_crawl_run(
    path: str | Path,
    run_id: int,
    status: str,
    raw_count: int,
    clean_count: int,
    stats: ObservationStats,
    errors: list[tuple[str, str]],
) -> None:
    now = _utc_now()
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        connection.executemany(
            "INSERT INTO crawl_errors(crawl_run_id,scope,error,occurred_at) VALUES(?,?,?,?)",
            [(run_id, scope, error, now) for scope, error in errors],
        )
        connection.execute(
            "UPDATE crawl_runs SET finished_at=?,status=?,raw_count=?,clean_count=?,"
            "new_count=?,changed_count=?,error_count=? WHERE id=?",
            (now, status, raw_count, clean_count, stats.new, stats.changed, len(errors), run_id),
        )
        connection.commit()


def save_observations(
    frame: pd.DataFrame,
    path: str | Path,
    run_id: int,
    observed_at: str,
) -> ObservationStats:
    """Upsert latest listing state and append one immutable observation per crawl run."""
    if frame.empty:
        return ObservationStats(seen=0, new=0, changed=0)
    rows = frame.copy()
    rows["listing_date"] = rows["listing_date"].astype(str)
    rows["url"] = rows.get("url", "").fillna("") if "url" in rows else ""
    new_count = 0
    changed_count = 0
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _ensure_schema(connection)
        for item in rows.to_dict(orient="records"):
            key = (str(item["source"]), str(item["source_listing_id"]))
            previous = connection.execute(
                "SELECT id,asking_price,mileage_km FROM listings WHERE source=? AND source_listing_id=?",
                key,
            ).fetchone()
            values = tuple(item[column] for column in COLUMNS)
            if previous is None:
                placeholders = ",".join("?" for _ in COLUMNS)
                cursor = connection.execute(
                    f"INSERT INTO listings ({','.join(COLUMNS)},first_seen_at,last_seen_at,seen_count) "
                    f"VALUES ({placeholders},?,?,1)",
                    values + (observed_at, observed_at),
                )
                listing_id = int(cursor.lastrowid)
                new_count += 1
                changed = True
            else:
                listing_id = int(previous[0])
                changed = float(previous[1]) != float(item["asking_price"]) or int(previous[2]) != int(item["mileage_km"])
                assignments = ",".join(f"{column}=?" for column in COLUMNS[2:])
                connection.execute(
                    f"UPDATE listings SET {assignments},last_seen_at=?,seen_count=seen_count+1 "
                    "WHERE id=?",
                    tuple(item[column] for column in COLUMNS[2:]) + (observed_at, listing_id),
                )
                changed_count += int(changed)
            fingerprint = sha256(
                json.dumps(
                    {column: str(item[column]) for column in COLUMNS[2:]},
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            connection.execute(
                "INSERT OR IGNORE INTO listing_observations"
                "(listing_id,crawl_run_id,observed_at,scope,asking_price,mileage_km,content_hash) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    listing_id,
                    run_id,
                    observed_at,
                    str(item.get("crawl_scope", item["source"])),
                    float(item["asking_price"]),
                    int(item["mileage_km"]),
                    fingerprint,
                ),
            )
        connection.commit()
    return ObservationStats(seen=len(rows), new=new_count, changed=changed_count)
