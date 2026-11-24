"""A case paused at the approval survives a restart (Postgres checkpointer) and executes once."""

import os

import psycopg
import pytest
from conftest import MC17_FACTS, MC17_MESSAGE, config
from langgraph.types import Command

from supplyguard_ai.graph import build_graph, make_checkpointer, pending

URL = os.getenv("TEST_DATABASE_URL", "postgresql://supplyguard:supplyguard@localhost:5433/supplyguard")


@pytest.fixture
def postgres_url():
    try:
        with psycopg.connect(URL, autocommit=True, connect_timeout=3) as conn:
            conn.execute("DROP TABLE IF EXISTS checkpoints, checkpoint_writes, checkpoint_blobs, checkpoint_migrations")
    except psycopg.OperationalError:
        pytest.skip("needs Postgres: docker compose up -d postgres")
    return URL


def test_resume_after_restart_executes_each_action_once(fake_llm, postgres_url):
    fake_llm(MC17_FACTS)
    first_app = build_graph(make_checkpointer(postgres_url))
    first = first_app.invoke({"case_id": "case-restart", "raw_text": MC17_MESSAGE}, config("case-restart"))
    request = pending(first)["request"]

    # "Restart": a brand-new app on the same database finds the case waiting for approval.
    app = build_graph(make_checkpointer(postgres_url))
    snapshot = app.get_state(config("case-restart"))
    assert snapshot.interrupts[0].value["request"]["payload_hash"] == request["payload_hash"]

    result = app.invoke(Command(resume="approve"), config("case-restart"))
    assert [e.status for e in result["executions"]] == ["done"] * 4
