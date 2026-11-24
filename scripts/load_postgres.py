"""LOAD_POSTGRES: every CSV in data/structured/ becomes one Postgres table. OWNER: role 2.

    uv run python scripts/load_postgres.py

How it works:
  - One table per file, with the same name and columns (inventory.csv -> table inventory).
  - Column types are guessed from the values: whole numbers -> BIGINT, decimals ->
    DOUBLE PRECISION, ISO dates like 2026-10-19 -> DATE, everything else -> TEXT.
  - Safe to run again: every table is dropped and loaded from scratch.

Data-quality problems are NOT fixed or hidden. The rows load exactly as the trainer
wrote them, and data_quality_manifest.csv becomes the table data_quality_manifest,
so the app can warn about them. At the end we also run a few checks of our own and
print what we found, to show we detect the problems, not just read the manifest.
"""

import os
import re
import sys
from pathlib import Path

import pandas as pd
import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from supplyguard_ai.config import data_dir, policies  # noqa: E402  (also loads .env)

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# 1. Guess a Postgres type for each column
# ---------------------------------------------------------------------------
def postgres_type(column: pd.Series) -> str:
    values = column.dropna()
    if pd.api.types.is_integer_dtype(column):
        return "BIGINT"
    if pd.api.types.is_float_dtype(column):
        # A column of whole numbers with a few blanks is read as float by pandas.
        return "BIGINT" if (values % 1 == 0).all() else "DOUBLE PRECISION"
    if len(values) and values.astype(str).str.match(ISO_DATE).all():
        return "DATE"
    return "TEXT"


def to_python(value):
    """pandas gives NaN for blanks and numpy numbers; Postgres wants None and plain Python."""
    if pd.isna(value):
        return None
    if hasattr(value, "item"):  # numpy.int64 -> int, numpy.float64 -> float
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


# ---------------------------------------------------------------------------
# 2. Load one CSV file into one table
# ---------------------------------------------------------------------------
def load_csv(conn: psycopg.Connection, path: Path) -> int:
    table = path.stem  # "inventory.csv" -> "inventory"
    # dtype=str for ID-like text is not needed: pandas keeps "S001", "MC-17" as text.
    frame = pd.read_csv(path)
    types = {name: postgres_type(frame[name]) for name in frame.columns}

    columns = sql.SQL(", ").join(
        sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(kind)) for name, kind in types.items()
    )
    conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table)))
    conn.execute(sql.SQL("CREATE TABLE {} ({})").format(sql.Identifier(table), columns))

    # COPY is Postgres' fast bulk load: we stream the rows instead of one INSERT each.
    copy_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, frame.columns))
    )
    with conn.cursor() as cursor, cursor.copy(copy_sql) as copy:
        for row in frame.itertuples(index=False):
            copy.write_row([to_python(value) for value in row])
    return len(frame)


# ---------------------------------------------------------------------------
# 3. Our own data-quality checks (the manifest is the answer key)
# ---------------------------------------------------------------------------
# label -> (our SQL query, the manifest's issue_type and file to compare with)
# %(day)s is the scenario date from policies.json (2026-10-19): "stale" is measured from it.
OWN_CHECKS = {
    "purchase orders with a blank component_id": (
        "SELECT count(*) FROM purchase_orders WHERE component_id IS NULL",
        "missing_identifier", "structured/purchase_orders.csv"),
    "purchase orders with a non-canonical component_id (e.g. 'MC173')": (
        "SELECT count(*) FROM purchase_orders WHERE component_id !~ '^MC-[0-9]+$'",
        "identifier_format", "structured/purchase_orders.csv"),
    "purchase orders delivered before they were ordered": (
        "SELECT count(*) FROM purchase_orders WHERE actual_delivery_date < order_date",
        "conflicting_dates", "structured/purchase_orders.csv"),
    # The manifest lists 6, but every in-transit update whose ETA had already passed
    # is suspicious (late, or a typo), so we flag all of them: the 6 are among ours.
    "in-transit shipment updates whose ETA is before the event date": (
        "SELECT count(*) FROM shipment_updates WHERE status = 'in_transit' AND eta < event_date",
        "conflicting_dates", "structured/shipment_updates.csv"),
    "supplier messages repeated (same day, sender and text)": (
        "SELECT count(*) - count(DISTINCT (received, sender, text)) FROM supplier_message_inbox",
        "duplicate_message", "structured/supplier_message_inbox.csv"),
    "inventory counts older than 180 days": (
        "SELECT count(*) FROM inventory WHERE last_counted_date < %(day)s::date - 180",
        "stale_record", "structured/inventory.csv"),
}


def main() -> None:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("Missing DATABASE_URL. Copy .env.example to .env (Postgres: docker compose up -d).")

    folder = data_dir() / "structured"
    files = sorted(folder.glob("*.csv"))
    print(f"Loading {len(files)} CSV files from {folder}")

    # autocommit=False: everything in one transaction, so a failure leaves no half-loaded tables.
    with psycopg.connect(url) as conn:
        for path in files:
            rows = load_csv(conn, path)
            print(f"  {path.stem:<32} {rows:>6} rows")
        conn.commit()

        print("\nData-quality checks (rows are kept as they are, not fixed)")
        print("  found  manifest")
        day = policies()["scenario_date"]
        for label, (query, issue, file) in OWN_CHECKS.items():
            found = conn.execute(query, {"day": day}).fetchone()[0]
            expected = conn.execute(
                "SELECT count(*) FROM data_quality_manifest WHERE issue_type = %s AND file = %s",
                (issue, file),
            ).fetchone()[0]
            mark = "ok" if found == expected else ("more" if found > expected else "FEWER")
            print(f"  {found:>5}  {expected:>8}  {mark:<9}  {label}")


if __name__ == "__main__":
    main()