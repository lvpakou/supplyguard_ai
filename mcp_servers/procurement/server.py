"""PostgreSQL-backed simulated procurement MCP server.

Run with `python server.py`. The server exposes read-only supply-chain queries
and approval-gated simulated writes. It never contacts a real ERP/procurement API.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# DNS-rebinding protection stays on, but also accepts the Docker service name. FastMCP's default
# (host 127.0.0.1) allows only localhost, and setting mcp.settings.host later does not change that:
# the chat container calls http://procurement-mcp:8000/mcp and got "Invalid Host header" (421).
ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*", "procurement-mcp:*"]
mcp = FastMCP("supplyguard-procurement", transport_security=TransportSecuritySettings(
    enable_dns_rebinding_protection=True, allowed_hosts=ALLOWED_HOSTS,
    allowed_origins=[f"http://{host}" for host in ALLOWED_HOSTS]))
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://supplyguard:supplyguard@localhost:5433/supplyguard",
)


def _connect():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _rows(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return [{k: _json_value(v) for k, v in row.items()} for row in cur.fetchall()]


def _one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    result = _rows(sql, params)
    return result[0] if result else None


def _ensure_operational_tables() -> None:
    """Create only MCP-owned operational tables; seed tables belong to role 2."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS procurement_approvals (
                approval_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('approved', 'consumed', 'revoked')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (approval_id, operation, payload_hash)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS procurement_idempotency (
                idempotency_key TEXT PRIMARY KEY,
                operation TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                result JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS procurement_action_audit (
                action_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                approval_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                operation TEXT NOT NULL,
                payload JSONB NOT NULL,
                result JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)


def _canonical_hash(operation: str, payload: dict[str, Any]) -> str:
    raw = json.dumps({"operation": operation, "payload": payload}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _approved(cur, approval_id: str, operation: str, payload: dict[str, Any]) -> bool:
    digest = _canonical_hash(operation, payload)
    cur.execute(
        "SELECT status FROM procurement_approvals WHERE approval_id=%s AND operation=%s AND payload_hash=%s FOR UPDATE",
        (approval_id, operation, digest),
    )
    row = cur.fetchone()
    return bool(row and row["status"] == "approved")


def _result(operation: str, status: str, message: str, reference: str | None = None,
            idempotency_key: str | None = None) -> dict[str, Any]:
    return {"operation": operation, "status": status, "message": message,
            "reference": reference, "idempotency_key": idempotency_key}


def _execute_write(operation: str, payload: dict[str, Any], approval_id: str,
                   idempotency_key: str) -> dict[str, Any]:
    _ensure_operational_tables()
    digest = _canonical_hash(operation, payload)
    with _connect() as conn, conn.cursor() as cur:
        # Serialize requests sharing a key, then return the first result unchanged.
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (idempotency_key,))
        cur.execute("SELECT operation, payload_hash, result FROM procurement_idempotency WHERE idempotency_key=%s",
                    (idempotency_key,))
        previous = cur.fetchone()
        if previous:
            if previous["operation"] != operation or previous["payload_hash"] != digest:
                return _result(operation, "refused", "idempotency_key was already used for a different action", idempotency_key=idempotency_key)
            first = dict(previous["result"])
            first["status"] = "already_done"
            return first

        if not approval_id or not _approved(cur, approval_id, operation, payload):
            return _result(operation, "refused", "no approved record matches this exact operation and payload", idempotency_key=idempotency_key)

        try:
            reference = _apply_action(cur, operation, payload)
        except (ValueError, LookupError) as exc:
            return _result(operation, "refused", str(exc), idempotency_key=idempotency_key)

        result = _result(operation, "done", "Simulated procurement action completed", reference, idempotency_key)
        cur.execute("UPDATE procurement_approvals SET status='consumed' WHERE approval_id=%s AND operation=%s AND payload_hash=%s",
                    (approval_id, operation, digest))
        cur.execute("INSERT INTO procurement_idempotency (idempotency_key, operation, payload_hash, result) VALUES (%s,%s,%s,%s::jsonb)",
                    (idempotency_key, operation, digest, json.dumps(result)))
        cur.execute("INSERT INTO procurement_action_audit (approval_id,idempotency_key,operation,payload,result) VALUES (%s,%s,%s,%s::jsonb,%s::jsonb)",
                    (approval_id, idempotency_key, operation, json.dumps(payload), json.dumps(result)))
        return result


def _apply_action(cur, operation: str, p: dict[str, Any]) -> str:
    if operation == "create_purchase_order":
        supplier = cur.execute("SELECT certification_status FROM suppliers WHERE supplier_id=%s", (p["supplier_id"],)).fetchone()
        if not supplier:
            raise LookupError("supplier_id does not exist")
        if str(supplier["certification_status"]).lower() != "valid":
            raise ValueError("supplier does not have valid certification")
        cap = float(os.getenv("PROCUREMENT_SPENDING_CAP_EUR", "75000"))
        if float(p["qty"]) * float(p["unit_price_eur"]) > cap:
            raise ValueError(f"purchase order exceeds spending cap of EUR {cap:.2f}")
        cur.execute("SELECT COALESCE(MAX(CAST(SUBSTRING(po_id FROM 8) AS INTEGER)),0)+1 AS n FROM purchase_orders WHERE po_id LIKE 'PO-MCP-%'")
        number = cur.fetchone()["n"]
        po_id = f"PO-MCP-{number:05d}"
        cur.execute("""INSERT INTO purchase_orders
            (po_id,supplier_id,supplier_name_as_entered,component_id,qty,unit_price_eur,order_date,promised_date,status,expedite_allowed)
            VALUES (%s,%s,(SELECT name FROM suppliers WHERE supplier_id=%s),%s,%s,%s,CURRENT_DATE,%s,'open','no')""",
            (po_id, p["supplier_id"], p["supplier_id"], p["component_id"], p["qty"], p["unit_price_eur"], p["requested_delivery_date"]))
        return po_id

    if operation == "expedite_purchase_order":
        row = cur.execute("SELECT promised_date, expedite_allowed, expedite_fee_pct FROM purchase_orders WHERE po_id=%s FOR UPDATE", (p["po_id"],)).fetchone()
        if not row:
            raise LookupError("po_id does not exist")
        if str(row["expedite_allowed"]).lower() not in ("yes", "true", "1"):
            raise ValueError("this purchase order cannot be expedited")
        if int(p["days_gain"]) <= 0 or not row["promised_date"]:
            raise ValueError("days_gain must be positive and the purchase order must have a promised date")
        new_date = row["promised_date"] - timedelta(days=int(p["days_gain"]))
        cur.execute("UPDATE purchase_orders SET promised_date=%s, expedite_fee_pct=%s WHERE po_id=%s",
                    (new_date, p["fee_pct"], p["po_id"]))
        return p["po_id"]

    if operation == "request_stock_transfer":
        qty = int(p["qty"])
        if qty <= 0:
            raise ValueError("qty must be positive")
        source = cur.execute("SELECT usable FROM inventory WHERE component_id=%s AND location_id=%s FOR UPDATE",
                             (p["component_id"], p["from_location"])).fetchone()
        destination = cur.execute("SELECT on_hand,reserved,quarantined FROM inventory WHERE component_id=%s AND location_id=%s FOR UPDATE",
                                  (p["component_id"], p["to_location"])).fetchone()
        if not source or not destination:
            raise LookupError("source or destination inventory row does not exist")
        if int(source["usable"]) < qty:
            raise ValueError(f"insufficient usable stock: {source['usable']} available, {qty} requested")
        cur.execute("UPDATE inventory SET on_hand=on_hand-%s, usable=usable-%s WHERE component_id=%s AND location_id=%s",
                    (qty, qty, p["component_id"], p["from_location"]))
        cur.execute("UPDATE inventory SET on_hand=on_hand+%s, usable=usable+%s WHERE component_id=%s AND location_id=%s",
                    (qty, qty, p["component_id"], p["to_location"]))
        return f"TRF-{p['component_id']}-{p['from_location']}-{p['to_location']}"

    if operation == "update_production_schedule":
        rows = cur.execute("SELECT factory_id FROM production_schedule WHERE product_id=%s AND week_start=%s FOR UPDATE",
                           (p["product_id"], p["week_start"])).fetchall()
        if len(rows) != 1:
            raise ValueError("production schedule must have exactly one matching product/week row; refusing an ambiguous or missing update")
        if int(p["planned_units"]) < 0:
            raise ValueError("planned_units cannot be negative")
        cur.execute("UPDATE production_schedule SET planned_units=%s WHERE product_id=%s AND week_start=%s",
                    (p["planned_units"], p["product_id"], p["week_start"]))
        return f"SCHEDULE-{p['product_id']}-{p['week_start']}"

    raise ValueError(f"unsupported operation: {operation}")


@mcp.tool()
def get_inventory(component_id: str) -> list[dict[str, Any]]:
    """Get on-hand, reserved, quarantined and usable inventory by location."""
    return _rows("SELECT * FROM inventory WHERE component_id=%s ORDER BY location_id", (component_id,))


@mcp.tool()
def get_open_purchase_orders(component_id: str | None = None, supplier_id: str | None = None) -> list[dict[str, Any]]:
    """List open purchase orders, optionally filtered by component_id and/or supplier_id."""
    if not component_id and not supplier_id:
        return _rows("SELECT * FROM purchase_orders WHERE lower(status)='open' ORDER BY promised_date")
    return _rows("SELECT * FROM purchase_orders WHERE lower(status)='open' AND (%s IS NULL OR component_id=%s) AND (%s IS NULL OR supplier_id=%s) ORDER BY promised_date",
                 (component_id, component_id, supplier_id, supplier_id))


@mcp.tool()
def get_supplier(supplier_id: str) -> dict[str, Any] | None:
    """Get supplier master data and certification status."""
    return _one("SELECT * FROM suppliers WHERE supplier_id=%s", (supplier_id,))


@mcp.tool()
def get_supplier_catalog(component_id: str) -> list[dict[str, Any]]:
    """List suppliers and their price, lead time, capacity and source status for a component."""
    return _rows("""SELECT sc.*, s.name AS supplier_name, s.country, s.erp_status,
                         s.certification_status, s.certification, s.certification_expiry
                  FROM supplier_components sc JOIN suppliers s USING (supplier_id)
                  WHERE sc.component_id=%s ORDER BY sc.unit_price_eur""", (component_id,))


@mcp.tool()
def get_customer_orders(product_id: str, due_before: str) -> list[dict[str, Any]]:
    """Get open customer orders for a product due before an ISO date (YYYY-MM-DD)."""
    return _rows("SELECT * FROM customer_orders WHERE product_id=%s AND due_date < %s AND lower(status)='open' ORDER BY due_date",
                 (product_id, due_before))


@mcp.tool()
def get_production_schedule(product_id: str) -> list[dict[str, Any]]:
    """Get the production schedule for a product, ordered by week and factory."""
    return _rows("SELECT * FROM production_schedule WHERE product_id=%s ORDER BY week_start,factory_id", (product_id,))


@mcp.tool()
def get_shipment_updates(po_id: str) -> list[dict[str, Any]]:
    """Get shipment tracking events for a purchase order."""
    return _rows("SELECT * FROM shipment_updates WHERE po_id=%s ORDER BY event_date,shipment_event_id", (po_id,))


@mcp.tool()
def create_purchase_order(supplier_id: str, component_id: str, qty: int, unit_price_eur: float,
                          requested_delivery_date: str, approval_id: str, idempotency_key: str) -> dict[str, Any]:
    """Create a simulated PO. Requires an exact-payload approval and unique idempotency key."""
    if qty <= 0 or unit_price_eur < 0:
        return _result("create_purchase_order", "refused", "qty must be positive and unit_price_eur cannot be negative", idempotency_key=idempotency_key)
    p = {"supplier_id": supplier_id, "component_id": component_id, "qty": qty,
         "unit_price_eur": unit_price_eur, "requested_delivery_date": requested_delivery_date}
    return _execute_write("create_purchase_order", p, approval_id, idempotency_key)


@mcp.tool()
def expedite_purchase_order(po_id: str, days_gain: int, fee_pct: float, approval_id: str,
                            idempotency_key: str) -> dict[str, Any]:
    """Expedite an eligible simulated PO; requires approval of this exact payload."""
    p = {"po_id": po_id, "days_gain": days_gain, "fee_pct": fee_pct}
    return _execute_write("expedite_purchase_order", p, approval_id, idempotency_key)


@mcp.tool()
def request_stock_transfer(component_id: str, from_location: str, to_location: str, qty: int,
                           approval_id: str, idempotency_key: str) -> dict[str, Any]:
    """Transfer usable stock between warehouses atomically; requires exact-payload approval."""
    if from_location == to_location:
        return _result("request_stock_transfer", "refused", "from_location and to_location must differ", idempotency_key=idempotency_key)
    p = {"component_id": component_id, "from_location": from_location,
         "to_location": to_location, "qty": qty}
    return _execute_write("request_stock_transfer", p, approval_id, idempotency_key)


@mcp.tool()
def update_production_schedule(product_id: str, week_start: str, planned_units: int,
                               approval_id: str, idempotency_key: str) -> dict[str, Any]:
    """Update one unambiguous product/week schedule row; requires exact-payload approval."""
    p = {"product_id": product_id, "week_start": week_start, "planned_units": planned_units}
    return _execute_write("update_production_schedule", p, approval_id, idempotency_key)


if __name__ == "__main__":
    _ensure_operational_tables()
    mcp.settings.host = os.getenv("MCP_HOST", "0.0.0.0")
    mcp.settings.port = int(os.getenv("MCP_PORT", "8000"))
    mcp.run(transport=os.getenv("MCP_TRANSPORT", "streamable-http"))
