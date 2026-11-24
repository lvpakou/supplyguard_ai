# approval_and_guardrails

OWNER: role 5. Write here as you build (5 lines a day is enough).

## Login and roles
- Chainlit password login (`chat_app.login`): username = a `user_id` from `data/config/users.csv`
  (`u-pm-01`, `u-an-01`, `u-ic-01`, `u-fc-01`, `u-ro-01`), password = `DEMO_PASSWORD` from `.env`.
- `users.csv` is trainer data with no passwords, so the demo uses one shared password. If it is
  missing, nobody can sign in (fail closed). Password compared with `hmac.compare_digest`.
- Every new case starts with the signed-in `user_id` and `user_role` (`chat_app.case_input`), so the
  graph and role 3's retrieval filter documents by that role (viewer: public only; only the
  finance controller sees finance-confidential).
- Limitation: one shared demo password, no per-user secrets. A real deployment would use SSO (OAuth).

## Approval (`approval.py`, `chat_app.py`)
- The request lists every exact action (supplier, quantity, unit price, date, cost), the total vs
  the cap, uncovered units, evidence ids, the challenge findings and warnings, and the payload hash.
- Tiers from `policies.json`: up to EUR 25k procurement_manager; up to 75k procurement_manager **and**
  finance_controller (two sign-offs, e.g. the EUR 30,378 MC-17 plan); up to 90k finance_director
  (nobody in users.csv: must be escalated); above that nobody can approve.
- Approve: only a role of the request's tier. Reject / Change: any approver role (they spend nothing).
- Every decision is a row in Postgres `approval_decisions` (requested / approve / reject / change, who,
  when, payload_hash, the requested change). A sign-off counts only for the payload_hash it was given
  for; a reject or change starts the sign-offs over.
- The graph is resumed with "approve" only when all roles have signed. The second approver sees the
  waiting request in their greeting, also after an application restart (checkpoint + audit table).
- Checked on the server for every click: the case comes from the session (never from the button), the
  payload_hash on the button must equal the paused request, the role must be allowed. Typed text never
  decides an approval.
- Resume value sent to the approval node: `{"decision", "change", "user_id", "user_role", "payload_hash"}`.
