"""benchmark_retrieval. OWNER: role 3.

Which search finds the right document: pgvector, ChromaDB or hybrid (pgvector + keywords)?
30 questions with known answers, plus off-topic questions to calibrate MIN_SIMILARITY.
Prints markdown tables to paste into docs/retrieval.md.

    docker compose up -d
    uv run python scripts/benchmark_retrieval.py
"""

import time

from supplyguard_ai.tools.retrieval import MIN_SIMILARITY, SEARCH_MODES, _search, get_embeddings

ROLE = "procurement_manager"
K = 5

# (kind, question, the documents that answer it). "meaning" = paraphrased, no shared keywords;
# "exact" = IDs and names, including near-duplicates (Quanta Systems vs Quanta Electronics).
QUESTIONS = [
    ("meaning", "Which supplier's quality certificate has run out?", {"DOC-QUA-S003-v1", "DOC-EM-BOREALIS-01"}),
    ("meaning", "How many units a month can Helios really deliver?", {"DOC-EM-HELIOS-01"}),
    ("meaning", "Who decides which document wins when two sources disagree?", {"DOC-PRO-02-v1"}),
    ("meaning", "Can we still order from a supplier whose certificate lapsed?", {"DOC-PRO-04-v1"}),
    ("meaning", "Is a second supplier real diversification if it uses the same upstream manufacturer?", {"DOC-PRO-05-v1"}),
    ("meaning", "Who has to approve a recovery plan that costs 60,000 euros?", {"DOC-PRO-03-v1"}),
    ("meaning", "Can the incident budget be raised above the normal limit?", {"DOC-EM-INTERNAL-01", "DOC-PRO-03-v1"}),
    ("meaning", "Can we use stock that is held in quarantine?", {"DOC-PRO-06-v1"}),
    ("meaning", "Which customer orders are protected first when parts are scarce?", {"DOC-PRO-07-v1"}),
    ("meaning", "What do we do with instructions hidden inside a supplier e-mail?", {"DOC-PRO-11-v1"}),
    ("meaning", "Should revenue at risk be added to the recovery cost?", {"DOC-PRO-12-v1"}),
    ("meaning", "The account manager hinted the delay could be longer than announced", {"DOC-EM-ATLAS-01"}),
    ("exact", "CERT-S003-72388", {"DOC-QUA-S003-v1"}),
    ("exact", "PO-2026-9002 expedite", {"DOC-EM-CORDILLERA-01"}),
    ("exact", "PO-2026-9001 MC-17 delay", {"DOC-NOT-ATLAS-MC17"}),
    ("exact", "Atlas Components supply contract", {"DOC-CON-S001-v3"}),
    ("exact", "Cordillera Industrial supply contract", {"DOC-CON-S004-v1"}),
    ("exact", "Delta Micro Systems ISO 9001 qualification record", {"DOC-QUA-S005-v1"}),
    ("exact", "HC-001 Borda Industrial MC-300", {"DOC-INC-HC-001"}),
    ("exact", "Quanta Electronics MC-2 notice", {"DOC-NOT-001", "DOC-NOT-025"}),
    # --- added: coverage of more document types ---
    ("meaning", "How do we work out what expediting a purchase order costs?", {"DOC-PRO-08-v1"}),
    ("meaning", "What sections must the final incident report contain?", {"DOC-PRO-09-v1"}),
    ("meaning", "What do we do if the message doesn't say which supplier is affected?", {"DOC-PRO-01-v1"}),
    ("meaning", "Are users allowed to see negotiated penalty rates?", {"DOC-PRO-10-v1"}),
    ("meaning", "Past incidents where the backup supplier was delayed too because of the same upstream manufacturer",
     {"DOC-INC-HC-009", "DOC-INC-HC-012", "DOC-INC-HC-022"}),
    ("exact", "Atlas Components committed monthly capacity", {"DOC-CON-S001-v3"}),
    ("exact", "Helios Supply contract late-delivery penalty", {"DOC-CON-S002-v1"}),
    ("exact", "Aurum Works MC-203 incident", {"DOC-INC-HC-007"}),
    ("exact", "CERT-S010-99086", {"DOC-QUA-S010-v1"}),
    ("exact", "Argo Dynamics MC-33 delay", {"DOC-NOT-010", "DOC-NOT-033"}),
]
# No document answers these: the best similarity here must stay BELOW MIN_SIMILARITY.
OFF_TOPIC = [
    "A recipe for moussaka",
    "Who won the football match yesterday?",
    "Weather forecast for Athens tomorrow",
    "How do I reset my laptop password?",
]


def first_hit(ranked: list[str], expected: set[str]) -> int | None:
    """1-based rank of the first right document, or None if it is not in the list."""
    return next((i for i, sid in enumerate(ranked, 1) if sid in expected), None)


def summarize(ranks: list[int | None], seconds: list[float]) -> dict:
    n = len(ranks)
    return {
        "hit@1": sum(r == 1 for r in ranks) / n,
        f"recall@{K}": sum(r is not None for r in ranks) / n,
        "MRR": sum(1 / r for r in ranks if r) / n,       # 1st = 1, 2nd = 0.5, missing = 0
        "ms": 1000 * sum(seconds) / n,
    }


def main() -> None:
    embeddings = get_embeddings()
    vectors = {q: embeddings.embed_query(q) for _, q, _ in QUESTIONS}   # same vector for every mode
    off_vectors = {q: embeddings.embed_query(q) for q in OFF_TOPIC}

    results, misses = {}, []
    for mode in SEARCH_MODES:
        ranks = {"meaning": [], "exact": []}
        seconds = []
        for kind, question, expected in QUESTIONS:
            start = time.perf_counter()
            rows = _search(question, ROLE, k=K, mode=mode, vector=vectors[question])
            seconds.append(time.perf_counter() - start)
            rank = first_hit([row[0] for row in rows], expected)
            ranks[kind].append(rank)
            if rank != 1:
                misses.append((mode, question, rank, [row[0] for row in rows[:3]]))
        results[mode] = {"all": summarize(ranks["meaning"] + ranks["exact"], seconds),
                         "meaning": summarize(ranks["meaning"], seconds),
                         "exact": summarize(ranks["exact"], seconds)}

    print(f"## Benchmark ({len(QUESTIONS)} questions, role {ROLE}, k={K})\n")
    print(f"| Mode | Hit@1 | Recall@{K} | MRR | Hit@1 meaning | Hit@1 exact | ms/query |")
    print("|---|---|---|---|---|---|---|")
    for mode, r in results.items():
        a = r["all"]
        print(f"| {mode} | {a['hit@1']:.2f} | {a[f'recall@{K}']:.2f} | {a['MRR']:.2f} | "
              f"{r['meaning']['hit@1']:.2f} | {r['exact']['hit@1']:.2f} | {a['ms']:.0f} |")

    print("\n### Not first (mode, question, rank of the right document, top 3)")
    for mode, question, rank, top in misses:
        print(f"- {mode}: {question!r} -> {rank or 'not found'} | {top}")

    # Calibration of _confident: the threshold must sit between these two numbers.
    def best(q, v):
        rows = _search(q, ROLE, k=1, mode="pgvector", vector=v)
        return rows[0][-1] if rows else 0.0
    on_topic = min((best(q, vectors[q]), q) for _, q, _ in QUESTIONS)
    off_topic = max((best(q, v), q) for q, v in off_vectors.items())
    print("\n### MIN_SIMILARITY calibration")
    print(f"- weakest right question: {on_topic[0]:.3f} ({on_topic[1]!r})")
    print(f"- strongest off-topic question: {off_topic[0]:.3f} ({off_topic[1]!r})")
    print(f"- current MIN_SIMILARITY: {MIN_SIMILARITY:.2f}")
    if off_topic[0] < on_topic[0]:
        print(f"- suggested: {(on_topic[0] + off_topic[0]) / 2:.2f} (halfway)")
    else:
        print("- no clean gap: some off-topic question scores higher than a right one; keep the threshold low")


if __name__ == "__main__":
    main()

    