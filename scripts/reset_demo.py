"""Forget old test cases and approvals before a demo. OWNER: role 1.

    uv run python scripts/reset_demo.py          # shows what would be deleted
    uv run python scripts/reset_demo.py --yes    # deletes it

Empties the saved cases (LangGraph checkpoint tables), the approval audit
(approval_decisions) and the procurement MCP server's records (approvals, idempotency,
audit). Approved actions also CHANGED the operational tables (stock transfers, new POs),
so run scripts/load_postgres.py afterwards to restore the trainer's data.
Use it on your own laptop's database, never on anything shared.
"""

import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from supplyguard_ai.config import database_url  # noqa: E402

TABLES = ["checkpoints", "checkpoint_writes", "checkpoint_blobs", "approval_decisions",
          "procurement_approvals", "procurement_idempotency", "procurement_action_audit"]


def main() -> None:
    url = database_url()
    if not url:
        raise SystemExit("DATABASE_URL is not set (see .env.example).")
    with psycopg.connect(url, autocommit=True) as conn:
        existing = {row[0] for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")}
        tables = [t for t in TABLES if t in existing]
        for table in tables:
            count = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            print(f"  {table:<20} {count} rows")
        if "--yes" not in sys.argv:
            print("Nothing deleted. Run again with --yes to empty these tables.")
            return
        if tables:
            conn.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables))
        if "incident_memories" in existing:   # memories of OUR test cases; the trainer's 40 stay
            deleted = conn.execute("DELETE FROM incident_memories WHERE source <> 'trainer'").rowcount
            print(f"  incident_memories    {deleted} memories of our own cases removed (trainer's kept)")
        print("Done: saved cases, approvals and procurement records are empty.")
        print("Now restore the operational data: uv run python scripts/load_postgres.py")


if __name__ == "__main__":
    main()
