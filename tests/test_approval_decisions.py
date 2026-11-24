"""What the user can answer at the approval: approve, reject, change, or ask a question."""

from conftest import MC17_FACTS, MC17_MESSAGE, config
from langgraph.types import Command

from supplyguard_ai.graph import build_graph, pending


def at_approval(fake_llm, thread):
    fake_llm(MC17_FACTS)
    app = build_graph()
    result = app.invoke({"case_id": thread, "raw_text": MC17_MESSAGE}, config(thread))
    assert pending(result)["type"] == "approval"
    return app


def test_change_is_kept_and_the_plan_goes_back_to_options_for_a_new_approval(fake_llm):
    app = at_approval(fake_llm, "case-change")

    result = app.invoke(Command(resume={"decision": "change", "qty": 6000}), config("case-change"))

    assert result["requested_change"] == {"qty": 6000}   # role 2's build_options reads this
    assert result["approval"].status == "changed"
    assert pending(result)["type"] == "approval"        # asked again, on the rebuilt plan
    assert result.get("executions", []) == []           # nothing bought


def test_free_text_change_is_kept_as_a_note(fake_llm):
    app = at_approval(fake_llm, "case-change-text")

    result = app.invoke(Command(resume="Change the quantity to 6,000"), config("case-change-text"))

    assert result["requested_change"] == {"note": "Change the quantity to 6,000"}


def test_a_question_at_the_approval_is_answered_and_never_counts_as_a_reject(fake_llm):
    app = at_approval(fake_llm, "case-question")

    result = app.invoke(Command(resume="Why did you reject Supplier Helios?"), config("case-question"))

    assert result["followups"][-1].question == "Why did you reject Supplier Helios?"
    assert result["approval"].status == "pending"       # still waiting for the decision
    assert pending(result)["type"] == "approval"
    assert result.get("executions", []) == []


def test_approve_after_a_change_clears_it_and_executes(fake_llm):
    app = at_approval(fake_llm, "case-change-approve")
    app.invoke(Command(resume={"decision": "change", "qty": 6000}), config("case-change-approve"))

    result = app.invoke(Command(resume="approve"), config("case-change-approve"))

    assert result["approval"].status == "approved"
    assert result["requested_change"] is None
    assert len(result["executions"]) == 4


# ---------------------------------------------------------------------------
# What the chat (role 5) really sends
# ---------------------------------------------------------------------------
def chat_payload(app, thread, decision, **extra):
    """The resume value chat_app.on_decide sends, with the current payload hash."""
    request = app.get_state(config(thread)).interrupts[0].value["request"]
    return {"decision": decision, "change": None, "user_id": "u-fc-01",
            "user_role": "finance_controller", "payload_hash": request["payload_hash"], **extra}


def test_chat_change_payload_becomes_the_agreed_format(fake_llm):
    app = at_approval(fake_llm, "case-chat-change")
    payload = chat_payload(app, "case-chat-change", "change", change="make the quantity 6,000")

    result = app.invoke(Command(resume=payload), config("case-chat-change"))

    # only the agreed keys reach build_options: no user_id / user_role / payload_hash
    assert result["requested_change"] == {"note": "make the quantity 6,000"}


def test_the_approver_who_clicked_is_recorded(fake_llm):
    app = at_approval(fake_llm, "case-chat-approve")

    result = app.invoke(Command(resume=chat_payload(app, "case-chat-approve", "approve")),
                        config("case-chat-approve"))

    assert result["approval"].decided_by == "u-fc-01"   # not the user who opened the case


def test_a_decision_on_an_older_plan_is_ignored(fake_llm):
    app = at_approval(fake_llm, "case-stale")
    stale = chat_payload(app, "case-stale", "approve") | {"payload_hash": "old-plan-hash"}

    result = app.invoke(Command(resume=stale), config("case-stale"))

    assert result["approval"].status == "pending"       # not approved
    assert result.get("executions", []) == []
    assert any("older plan" in w for w in result["warnings"])
