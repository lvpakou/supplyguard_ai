# red_team

OWNER: role 5. Write here as you build (5 lines a day is enough).

| # | Attack | Before | Now |
|---|---|---|---|
| 1 | Type "approve" in the chat while the case waits for approval | The text resumed the graph: approved and executed, no role check | Typed text never decides; the chat points to the buttons |
| 2 | Send the Approve action with another case's `thread_id` in its payload | The other case was resumed | The case comes from the server-side session; opening a case checks the role |
| 3 | Viewer / operations analyst clicks Approve (forged action) | Allowed | Refused on the server: the role must belong to the request's tier |
| 4 | Approve a plan, then the plan changes (supplier / qty / price) | Old approval could apply | The button carries the payload_hash; a mismatch shows the new request; sign-offs only count for their hash |
| 5 | One procurement manager approves a EUR 30k plan alone | Executed | Needs the finance controller too (tier "procurement_manager + finance_controller") |
