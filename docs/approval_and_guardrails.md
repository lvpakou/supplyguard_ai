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
