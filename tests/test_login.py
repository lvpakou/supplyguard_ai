"""Chat login (role 5): a users.csv user_id + the demo password; the role travels into the case."""

import asyncio

import pytest
from conftest import MC17_FACTS, MC17_MESSAGE, config

from supplyguard_ai import chat_app
from supplyguard_ai.graph import build_graph


@pytest.fixture(autouse=True)
def demo_password(monkeypatch):
    monkeypatch.setenv("DEMO_PASSWORD", "test-pass")


def login(username: str, password: str):
    return asyncio.run(chat_app.login(username, password))


def test_a_known_user_signs_in_with_their_role():
    user = login("u-fc-01", "test-pass")
    assert user.identifier == "u-fc-01"
    assert user.metadata == {"name": "Paul Novak", "role": "finance_controller"}


def test_wrong_password_or_unknown_user_is_refused():
    assert login("u-pm-01", "wrong") is None
    assert login("u-nobody", "test-pass") is None


def test_nobody_signs_in_when_no_password_is_configured(monkeypatch):
    monkeypatch.delenv("DEMO_PASSWORD")
    assert login("u-pm-01", "") is None


def test_a_new_case_runs_as_the_signed_in_user(fake_llm):
    fake_llm(MC17_FACTS)
    viewer = login("u-ro-01", "test-pass")

    result = build_graph().invoke(chat_app.case_input("case-viewer", MC17_MESSAGE, viewer),
                                  config("case-viewer"))

    assert (result["user_id"], result["user_role"]) == ("u-ro-01", "viewer")
