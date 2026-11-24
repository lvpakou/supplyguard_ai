"""TABLES: read one table of the trainer's data, the same way for every role-2 tool. OWNER: role 2.

Where the rows come from:
  - Postgres, if DATABASE_URL is set and the database answers (after scripts/load_postgres.py).
  - Otherwise straight from data/structured/<name>.csv. Same rows either way, because the
    loader copies the CSVs unchanged. This keeps the tests running on a laptop without Docker.

Date columns are turned into real dates in both cases, so `due_date <= day` works.
"""

import os

import pandas as pd
import psycopg
from psycopg import sql

from supplyguard_ai.config import data_dir

# Columns holding dates in the trainer's tables.
DATE_COLUMNS = {
    "last_counted_date", "due_date", "order_date", "promised_date", "actual_delivery_date",
    "event_date", "eta", "week_start", "received", "date", "certification_expiry",
    "effective_date", "release_expected",
}


def _from_postgres(name: str) -> pd.DataFrame | None:
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    try:
        with psycopg.connect(url, connect_timeout=2) as conn, conn.cursor() as cursor:
            cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(name)))
            columns = [column.name for column in cursor.description]
            return pd.DataFrame(cursor.fetchall(), columns=columns)
    except psycopg.Error:
        return None  # not running, or the table is not loaded yet: use the CSV


def table(name: str) -> pd.DataFrame:
    """All rows of one table, e.g. table("inventory")."""
    frame = _from_postgres(name)
    if frame is None:
        frame = pd.read_csv(data_dir() / "structured" / f"{name}.csv")
    for column in DATE_COLUMNS & set(frame.columns):
        # errors="coerce": a value that is not a date (e.g. "unknown") becomes NaT, not a crash.
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame
