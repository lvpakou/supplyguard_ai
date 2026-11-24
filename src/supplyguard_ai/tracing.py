"""LangSmith: how our runs appear there, and a quick check of the settings. OWNER: role 1.

Tracing itself needs no code: LangChain and LangGraph send every run to LangSmith when
.env has LANGSMITH_TRACING=true, LANGSMITH_API_KEY, LANGSMITH_ENDPOINT (EU accounts) and
LANGSMITH_PROJECT. This file adds what makes the traces easy to find:
  - every run is named "SupplyGuard case" and tagged with its source ("chat", "evaluation");
  - every run carries the case's thread_id as metadata, so LangSmith's Threads tab groups
    all runs of one case (first message, clarifications, approval, follow-ups).

Check your settings:  uv run python -m supplyguard_ai.tracing
"""

import os

from supplyguard_ai import config  # noqa: F401  (loads .env)

RUN_NAME = "SupplyGuard case"


def run_config(thread_id: str, source: str, **metadata) -> dict:
    """The config for graph.invoke / graph.astream of one case."""
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": RUN_NAME,
        "tags": [source],
        "metadata": {"thread_id": thread_id, "source": source, **metadata},
    }


def tracing_enabled() -> bool:
    return os.getenv("LANGSMITH_TRACING", "").strip().lower() == "true"


def status_line() -> str:
    if not tracing_enabled():
        return "LangSmith tracing: off (LANGSMITH_TRACING=true in .env turns it on)"
    if not os.getenv("LANGSMITH_API_KEY"):
        return "LangSmith tracing: LANGSMITH_TRACING=true but LANGSMITH_API_KEY is empty"
    return f"LangSmith tracing: on, project '{os.getenv('LANGSMITH_PROJECT') or 'default'}'"


def check() -> int:
    """Connect to LangSmith with the .env settings and say what works."""
    print(status_line())
    if not os.getenv("LANGSMITH_API_KEY"):
        return 1
    from langsmith import Client

    try:
        list(Client().list_projects(limit=1))
    except Exception as error:  # wrong key, wrong region (EU vs US), no network
        print(f"Could not connect: {type(error).__name__}: {str(error)[:200]}")
        print("Check the key and LANGSMITH_ENDPOINT (EU accounts: https://eu.api.smith.langchain.com).")
        return 1
    print("Connected: the key works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(check())
