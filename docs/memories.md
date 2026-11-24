# Incident memories

OWNER: role 3 (`src/supplyguard_ai/memory.py`).

The system's experience: approved resolutions of past incidents, used to tell the user
"a similar case was solved with X, and the lesson was Y".

## Setup (once per laptop)
```bash
docker compose up -d
uv run python scripts/index_documents.py --only memories   # only the memories (fast)
```
The full `scripts/index_documents.py` also loads them, after the documents.
Expect: `memories: 40 rows in 'incident_memories'`.

## Where they live
Table `incident_memories` in Postgres (pgvector), separate from `documents`:

| Column | Meaning |
|---|---|
| `memory_id` | `MEM-HC-001` (trainer) or `MEM-CASE-<case_id>` (our own approved cases) |
| `case_id` | unique: one memory per case |
| `component_id`, `supplier_id`, `strategy` | what the case was about and how it was solved |
| `summary` | one line, e.g. "certification lapse (8 d) resolved with 'Purchase from an approved alternative' at EUR 39,170. Alternative supplier needed qualification check first." |
| `access_scope` | `internal` for all of them |
| `source` | `trainer` or `approved case` |
| `embedding` | vector of the summary + component, supplier and strategy |

**The table is never dropped.** It also holds the cases our app resolved, and re-indexing must
not lose them. The trainer's 40 memories are updated (upsert); our own cases are kept.

The trainer's summaries never name the component or the supplier, so before embedding we add
them ("… Component MC-300, supplier Borda Industrial (S049). Strategy: …"). Otherwise a
search for "Atlas MC-17" could not find anything.

## How they are used
1. **Finding similar cases:** `similar_cases(text, k=3, user_role=...)`. The evidence step searches
   with "<supplier> <component> <N>-day delay" and adds the results to the evidence as
   `MEM-…` items (`as_evidence`), with their source.
   - **Role filter:** all memories are `internal`, so a viewer sees none; without a role,
     nothing is returned (least access).
   - **Threshold:** each memory must reach `MIN_SIMILARITY` (0.30): "similar" must mean similar.
   - **Injection guard:** memories go through `guards.check_injection()` like documents.
   - **Not required:** if the table is missing, the case continues with a warning
     ("Incident memories not available: … run index_documents.py").
   - `find_conflicts` ignores them (they are not supplier documents).
2. **Saving a resolved case:** `save_resolution(state)`, called by the report step.
   - **Only approved cases**, and only if no action was refused (a refused plan was not carried out).
   - **Never twice:** after a restart the report step runs again; the first memory is kept.
   - **Never breaks the report:** if the database or Azure is down, a warning is logged and the
     report still comes. The case is already closed.

## Memory poisoning
A saved summary is built **only from our own structured fields**: facts, plan, cost, the
conflicts we resolved, and the *number* of documents ignored as injection. It never copies
the user's message or a warning's text. Otherwise an injection like "Ignore previous
instructions…" would be stored as a lesson and handed to every future similar case.

Example of a saved summary (MC-17):
> delay (12 d) of MC-17 from Atlas Components resolved with 'A Transfer from the hub + B Expedite
> PO-2026-9002 + C Buy from Cordillera' at EUR 30,378. Lessons: Atlas Components (S001) delay MC-17:
> used 12 days; 1 document(s) ignored as prompt injection; 850 units not covered (reschedule (E)).

## Tests (`tests/test_memory.py`, 11)
- Without services: the 40 memories load; the embedded text names component and supplier;
  the summary keeps the lessons but never the injection; rejected / refused cases never touch
  the database; a database failure does not raise; the evidence step adds memories and survives
  a missing table.
- Live (Docker + memories loaded + Azure keys): a certification lapse finds `MEM-HC-051`;
  a viewer or no role gets nothing; an approved case is saved once and found by a later search
  (the test deletes its row afterwards).

Graph tests never read or write real memories: `conftest.py` fakes `similar_cases` and
`save_resolution`.