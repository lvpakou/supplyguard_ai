"""STATE: the shared data model of SupplyGuard AI (the "interfaces").

Every role reads and returns these classes, so the five branches fit together.
RULE: only role 1 changes this file, after telling the team (small PR, merged at once).

LangGraph passes one CaseState from node to node. A node returns a dict with only
the fields it changes; LangGraph merges it into the state.
"""

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 1. What the procurement manager told us (filled by the intake node, via the LLM)
# ---------------------------------------------------------------------------
class IncidentFacts(BaseModel):
    """Facts about a supply disruption, taken only from what the user wrote.

    Leave a field null when the message does not say it. Never guess an ID.
    """

    supplier_name: str | None = Field(
        default=None, description="Supplier name as written, e.g. 'Atlas Components'."
    )
    supplier_id: str | None = Field(
        default=None,
        description="Supplier ID like 'S001' ONLY if it is certain from the message. "
        "Null if the name is ambiguous (e.g. just 'Atlas').",
    )
    component_id: str | None = Field(
        default=None, description="Component ID like 'MC-17'. Null if not stated."
    )
    delay_days: int | None = Field(
        default=None, description="Announced delay in days, e.g. 12. Null if not stated."
    )
    spending_cap_eur: float = Field(
        default=75000, description="Maximum extra spend in EUR the user allows. Default 75000."
    )
    ambiguities: list[str] = Field(
        default=[],
        description="Things that must be clarified before acting, e.g. "
        "\"'Atlas' could be Atlas Components (S001) or Atlas Logistik\".",
    )


class Clarification(BaseModel):
    question: str
    answer: str


# ---------------------------------------------------------------------------
# 2. Operational impact (role 2: deterministic calculations)
# ---------------------------------------------------------------------------
class ImpactSummary(BaseModel):
    component_id: str
    on_hand: int
    reserved: int
    quarantined: int
    usable: int                                   # on_hand - reserved - quarantined
    usable_by_location: dict[str, int] = {}       # e.g. {"W-STU": 1300, "W-HUB": 800}
    daily_demand: int                             # units/day over all plants
    days_of_cover: dict[str, float] = {}          # e.g. {"F3 (W-LYO)": 3.3}
    first_stockout_day: int | None = None
    shortfall_units: int                          # demand not covered until the delayed delivery
    affected_products: list[str] = []
    open_orders_at_risk: int = 0
    revenue_at_risk_eur: float | None = None      # reported SEPARATELY from recovery cost
    source_ids: list[str] = []                    # tables/rows the numbers come from


# ---------------------------------------------------------------------------
# 3. Evidence from documents (role 3) and the graph (role 4)
# ---------------------------------------------------------------------------
class Evidence(BaseModel):
    """One claim with its provenance. Every number shown to the user has one."""

    claim: str
    source_id: str                    # e.g. "DOC-CON-S001-v3"
    doc_type: str = ""                # contract, qualification, supplier_notice, email, ...
    version: str | None = None
    effective_date: str | None = None
    access_scope: str = "internal"    # public / internal / procurement / finance-confidential


class Conflict(BaseModel):
    """Two sources disagree; we keep the one with higher precedence (policies.json)."""

    topic: str                        # e.g. "Atlas delay"
    values: dict[str, str]            # source_id -> value, e.g. {"DOC-NOT-...": "12 d", "DOC-EML-...": "16 d"}
    chosen: str                       # the value we use
    reason: str                       # e.g. "supplier notice outranks supplier e-mail"


class SupplierCheck(BaseModel):
    """An alternative supplier for the component, as the graph and documents describe it."""

    supplier_id: str
    name: str
    unit_price_eur: float | None = None
    lead_time_days: int | None = None
    monthly_capacity: int | None = None
    certification_valid: bool = True
    shared_upstream_with: list[str] = []   # e.g. ["S001"] -> same upstream manufacturer as Atlas
    risk_alerts: list[str] = []            # from the external risk service
    notes: list[str] = []


# ---------------------------------------------------------------------------
# 4. Recovery options (role 2) and the approval (role 5)
# ---------------------------------------------------------------------------
Operation = Literal[
    "create_purchase_order",
    "expedite_purchase_order",
    "request_stock_transfer",
    "update_production_schedule",
]


class Action(BaseModel):
    """One write operation on the simulated procurement system (MCP), with its exact payload."""

    operation: Operation
    payload: dict                     # exactly the fields in procurement_system_operations.json
    cost_eur: float = 0.0


class Option(BaseModel):
    """One recovery strategy, fully costed."""

    strategy: Literal["A", "B", "C", "D", "E"]  # A transfer, B expedite, C buy alternative, D reallocate, E reschedule
    title: str
    actions: list[Action] = []
    cost_eur: float = 0.0
    covered_units: int = 0
    uncovered_units: int = 0
    feasible: bool = True
    rejected_because: str | None = None
    evidence_ids: list[str] = []


class Recommendation(BaseModel):
    """The plan we propose: one or more options combined (e.g. A + B + C)."""

    summary: str
    options: list[Option]
    total_cost_eur: float
    uncovered_units: int = 0
    residual_handling: str | None = None    # e.g. "850 units: reschedule (E) or reallocate (D)"


class ApprovalRequest(BaseModel):
    """What the human approves. Bound to the exact payload: any change -> new approval."""

    approval_id: str
    payload_hash: str                 # hash of every action payload
    total_cost_eur: float
    approver_role: str                # from the approval tiers in policies.json
    status: Literal["pending", "approved", "rejected", "changed"] = "pending"
    decided_by: str | None = None


class ExecutionResult(BaseModel):
    operation: Operation
    idempotency_key: str              # case_id + step: the same key never runs twice
    status: Literal["done", "already_done", "refused"]
    reference: str | None = None      # e.g. the new PO number
    message: str = ""


class FollowUp(BaseModel):
    question: str
    answer: str


# ---------------------------------------------------------------------------
# The case: everything the graph knows about one incident
# ---------------------------------------------------------------------------
class CaseState(BaseModel):
    case_id: str
    user_id: str = "u-pm-01"
    user_role: str = "procurement_manager"
    raw_text: str

    facts: IncidentFacts | None = None
    clarifications: list[Clarification] = []
    needs_clarification: list[str] = []

    impact: ImpactSummary | None = None
    evidence: list[Evidence] = []
    conflicts: list[Conflict] = []
    warnings: list[str] = []                  # injection found, stale data, data-quality problems
    supplier_checks: list[SupplierCheck] = []
    investigation_notes: list[str] = []       # from the Deep Agent

    options: list[Option] = []
    recommendation: Recommendation | None = None
    critique: list[str] = []                  # what the challenge step found

    approval: ApprovalRequest | None = None
    executions: list[ExecutionResult] = []
    report: str | None = None
    followups: list[FollowUp] = []
