"""Shared test helpers: the fake LLM (no Azure calls) and the case config."""

import os

os.environ.setdefault("LANGSMITH_TRACING", "false")  # fast tests send nothing to LangSmith
os.environ.pop("LLM_CACHE", None)                    # tests never use the local answer cache

import pytest  # noqa: E402

from supplyguard_ai import nodes  # noqa: E402
from supplyguard_ai.state import IncidentFacts  # noqa: E402

MC17_MESSAGE = (
    "Supplier Atlas Components has announced a 12-day delay for component MC-17. "
    "Determine which customer commitments are at risk, investigate alternative sources, and "
    "recommend a recovery plan. Additional spending must not exceed €75,000. "
    "Do not create a purchase order without approval."
)
MC17_FACTS = IncidentFacts(supplier_name="Atlas Components", component_id="MC-17", delay_days=12,
                           spending_cap_eur=75000)


class FakeLLM:
    """Pretends to be the chat model: returns the given answers in order."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def with_structured_output(self, schema):
        return self

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        return self.answers[len(self.calls) - 1]


@pytest.fixture(autouse=True)
def no_mcp_servers(monkeypatch):
    """Fast tests never write to the real procurement system: in-memory fake, HTTP risk feed."""
    # Empty, not deleted: some modules call load_dotenv() again, which would bring back
    # a deleted variable from .env, but never overwrites one that is set.
    monkeypatch.setenv("PROCUREMENT_MCP_URL", "")
    monkeypatch.setenv("RISK_MCP_URL", "")


@pytest.fixture
def fake_llm(monkeypatch):
    def install(*answers):
        fake = FakeLLM(answers)
        monkeypatch.setattr(nodes, "get_llm", lambda: fake)
        return fake
    return install


def config(thread_id: str = "case-test") -> dict:
    return {"configurable": {"thread_id": thread_id}}


@pytest.fixture(autouse=True)
def no_real_search(monkeypatch):
    """Graph tests run without Docker or Azure: the evidence step finds no documents.

    The real search is tested directly in test_retrieval.py (it imports search_documents
    from tools.retrieval, so this patch doesn't touch it).
    """
    monkeypatch.setattr(nodes, "search_documents", lambda *args, **kwargs: [])


@pytest.fixture(autouse=True)
def no_real_memory(monkeypatch):
    """Graph tests never read or write incident memories in the real database (memory.py is tested directly)."""
    monkeypatch.setattr(nodes, "save_resolution", lambda state: None)
    monkeypatch.setattr(nodes, "similar_cases", lambda *args, **kwargs: [])


@pytest.fixture(autouse=True)
def no_real_contract_agent(monkeypatch):
    """Graph tests never call Azure for the contract agent (tests/test_contract_agent.py tests it directly)."""
    monkeypatch.setattr(nodes, "analyze_contracts", lambda *args, **kwargs: [])


@pytest.fixture(autouse=True)
def no_real_investigator(monkeypatch):
    """Graph tests never call Azure for the Deep Agent (tests/test_investigator.py tests it directly)."""
    monkeypatch.setattr(nodes, "investigate", lambda *args, **kwargs: [])

    