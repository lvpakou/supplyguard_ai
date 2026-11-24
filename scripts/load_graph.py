"""load_graph. OWNER: role 4.

TODO: run data/graph/load.cypher on Neo4j (the CSVs are mounted at /var/lib/neo4j/import)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CYPHER_FILE = PROJECT_ROOT / "data" / "graph" / "load.cypher"


def _statements_from_file(path: Path) -> list[str]:
    """Return executable Cypher statements, ignoring blank and comment lines.

    load.cypher intentionally has one complete statement per line. Keeping
    statements separate is important because the Neo4j Python driver sends
    one Cypher statement per session.run() call.
    """
    statements: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        statement = line.strip().removesuffix(";")
        if not statement or statement.startswith("//"):
            continue
        statements.append(statement)
    return statements


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    username = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")

    if not password:
        raise RuntimeError(
            "NEO4J_PASSWORD is not set. Add it to the project .env file "
            "or export it in your environment."
        )
    if not CYPHER_FILE.is_file():
        raise FileNotFoundError(f"Neo4j seed file not found: {CYPHER_FILE}")

    statements = _statements_from_file(CYPHER_FILE)
    if not statements:
        raise RuntimeError(f"No Cypher statements found in {CYPHER_FILE}")

    print(f"Connecting to Neo4j at {uri}...")
    with GraphDatabase.driver(uri, auth=(username, password)) as driver:
        driver.verify_connectivity()
        with driver.session() as session:
            for index, statement in enumerate(statements, start=1):
                try:
                    session.run(statement).consume()
                except Exception as exc:
                    raise RuntimeError(
                        f"Failed while executing statement {index}/{len(statements)} "
                        f"from {CYPHER_FILE.name}: {statement[:160]}"
                    ) from exc
                print(f"[{index}/{len(statements)}] executed")

            # Report what was loaded so the user can quickly verify the seed.
            labels = ("Supplier", "Upstream", "Component", "Product", "Factory", "Customer")
            print("\nNode counts:")
            for label in labels:
                result = session.run(
                    f"MATCH (n:{label}) RETURN count(n) AS count"
                ).single()
                print(f"  {label}: {result['count']}")

            relationship_result = session.run(
                "MATCH ()-[r]->() RETURN count(r) AS count"
            ).single()
            print(f"Relationships: {relationship_result['count']}")

    print("\nNeo4j graph seeding completed successfully.")


if __name__ == "__main__":
    main()
