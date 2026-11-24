"""Resume a saved case: list the user's cases (newest first) and reopen one after a restart."""

from conftest import MC17_FACTS, MC17_MESSAGE, config

from supplyguard_ai.graph import build_graph, is_resume_request, make_checkpointer, recent_cases


def test_resume_requests_are_recognised():
    assert is_resume_request("Resume the case I was reviewing yesterday.")
    assert is_resume_request("resume")
    assert is_resume_request("Continue my case")
    assert not is_resume_request("Why did you reject Supplier Helios?")


def test_a_new_app_finds_the_users_cases_newest_first(fake_llm):
    fake_llm(MC17_FACTS, MC17_FACTS, MC17_FACTS)
    saver = make_checkpointer(None)
    app = build_graph(saver)
    for case, user in (("older", "u-pm-01"), ("other-user", "u-fc-01"), ("newer", "u-pm-01")):
        app.invoke({"case_id": case, "raw_text": MC17_MESSAGE, "user_id": user}, config(case))

    restarted = build_graph(saver)                       # "the next day"
    cases = recent_cases(restarted, user_id="u-pm-01")

    assert [c["case_id"] for c in cases] == ["newer", "older"]   # only mine, newest first
    assert cases[0]["status"] == "waiting for approval"
    assert cases[0]["request"].startswith("Supplier Atlas Components")


def test_resume_case_scores_in_the_evaluation(fake_llm):
    from supplyguard_ai.evaluation import Runner, load_cases, run_case, score

    fake_llm(MC17_FACTS)
    case = next(c for c in load_cases() if c["id"] == "EV-0085")
    result = score(case, run_case(case, Runner()), use_judge=False)
    assert result["score"] == 1, result["comment"]
