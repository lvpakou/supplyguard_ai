# Follow-up questions

OWNER: role 5 (`src/supplyguard_ai/followup.py`, chat part in `chat_app.py`).

## How an answer is made
1. **Guard:** a question that tries to give the agent orders (`guards.check_injection`) is refused
   with a fixed answer. The LLM is not called.
2. **What-ifs:** numbers that change are recomputed with role 2's deterministic tools before the LLM
   sees them:
   - an amount in EUR of at least 1,000 ("EUR 90,000", "€90k"): the options again with that cap;
   - a number of days other than the announced delay ("16 days"): the impact again with that delay.
     A contract *lead time* is not a delay, so it never triggers this;
   - priority customers ("highest-priority", "tier 1"): tier-1 orders at risk against usable stock.
3. **Case file:** JSON of the saved state: facts, impact, supplier checks, all options with the
   reasons for rejecting them, recommendation, challenge, conflicts, warnings, decision,
   requested change, executions, policies and the last 3 questions. The incident message is wrapped
   as untrusted data.
4. **Documents:** only the case's evidence in the scopes its role may read, each wrapped with
   `guards.wrap_untrusted`.
5. **LLM** (`llm.get_llm`): answers only from the above. It must refuse policy breaks, superseded
   or lower-precedence sources, double-counted penalties, and data outside the role's scopes.
   If the model cannot be reached, a short answer is built from the case file alone.

## In the chat
- A question typed while the approval waits is answered by the approval node (role 1). The chat
  shows the answer and says the request is still waiting. Typed approve/reject/change words are
  still blocked: only the buttons decide.
- After the decision, every message is a follow-up question; the answer is shown below the report.

## Results (`scripts/run_evaluation.py --local`, with the LLM judge)
| Category | Before | Now |
|---|---|---|
| follow_up | 0/4 | 4/4 |
| policy_and_authorization | 0/10 | 9/10 |

The remaining failure is EV-0096 ("change quantity to 6,000"). The approval node keeps the change,
but `build_options` (role 2) does not apply `requested_change` yet, so the plan and its hash stay the same.
