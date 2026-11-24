"""What a chat message means: new case, answer to the paused step, or "new"."""

from langgraph.types import Command

from supplyguard_ai.chat_app import route_message


def test_first_message_starts_a_new_case():
    thread_id, graph_input, reply = route_message(None, "MC-17 is late")
    assert thread_id is not None
    assert graph_input == {"case_id": thread_id, "raw_text": "MC-17 is late"}
    assert reply is None


def test_message_in_an_open_case_answers_the_paused_step():
    thread_id, graph_input, _ = route_message("case-1", "Atlas Components")
    assert thread_id == "case-1"
    assert isinstance(graph_input, Command) and graph_input.resume == "Atlas Components"


def test_new_forgets_the_case_and_the_next_message_starts_a_fresh_one():
    # The bug: after "new" the next message was sent as an answer to a case that never started.
    thread_id, graph_input, reply = route_message("case-1", "new")
    assert (thread_id, graph_input) == (None, None)
    assert reply == "OK, describe the next disruption."

    thread_id, graph_input, _ = route_message(thread_id, "Atlas says the motor board is late.")
    assert thread_id not in (None, "case-1")
    assert graph_input["raw_text"] == "Atlas says the motor board is late."
