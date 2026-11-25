# retrieval

OWNER: role 3. Write here as you build (5 lines a day is enough).

## Search modes
- `hybrid` (default): pgvector (meaning) + Postgres full text (exact words), merged with
  reciprocal rank fusion. The keyword side requires ALL words of the question, so it only
  speaks for exact IDs and names (CERT-…, PO-…, "Quanta Electronics" vs "Quanta Systems").
- `pgvector`, `chroma`: meaning only. Chroma applies the same role/version rules.
- `RETRIEVAL_MODE` / `RETRIEVAL_MIN_SIMILARITY` in `.env` override the defaults.
- `_confident`: an open search whose best match is below 0.30 returns nothing ("no reliable
  source"). Searches with a filter (e.g. one supplier) skip it: the caller named what it wants.

## Benchmark (`scripts/benchmark_retrieval.py`, 20 questions, procurement_manager, k=5)
| Mode | Hit@1 | Recall@5 | MRR | Hit@1 meaning | Hit@1 exact | ms/query |
|---|---|---|---|---|---|---|
| hybrid v1 (any word) | 0.75 | 0.90 | 0.82 | 0.67 | 0.88 | 27 |
| **hybrid (all words)** | **0.95** | **1.00** | **0.96** | 0.92 | **1.00** | 27 |
| pgvector | 0.90 | 0.95 | 0.91 | 0.92 | 0.88 | 23 |
| chroma | 0.90 | 0.95 | 0.91 | 0.92 | 0.88 | 156 |

- v1 matched ANY word: common words ("supplier", "certificate") matched all 60 contracts and
  pushed them up. Requiring ALL words fixed it.
- pgvector and Chroma hold the same vectors, so same accuracy; Chroma is ~6x slower → pgvector.
- Embeddings blur codes: pgvector never finds `CERT-S003-72388`; hybrid does.
- Still missed by every mode: "Which supplier's quality certificate has run out?" → the expired
  record is 5th; the procedure on expired certificates (PRO-04) comes first.
- MIN_SIMILARITY: weakest right question 0.458, strongest off-topic 0.177 → 0.30 is safely between.

## Benchmark v2 (2026-11-25, 30 questions, procurement_manager, k=5)
Added 10 questions: 4 procedures (PRO-01, 08, 09, 10), incident reports, two more
contracts, a second certificate number, and a supplier with two notices (Argo MC-33).

| Mode | Hit@1 | Recall@5 | MRR | Hit@1 meaning | Hit@1 exact | ms/query |
|---|---|---|---|---|---|---|
| **hybrid** | **0.87** | **0.97** | **0.90** | 0.76 | **1.00** | 60 |
| pgvector | 0.80 | 0.93 | 0.84 | 0.76 | 0.85 | 39 |
| chroma | 0.80 | 0.93 | 0.84 | 0.76 | 0.85 | 323 |

- No regression: the original 20 questions still score 19/20 with hybrid (only the known
  expired-certificate miss). The drop from 0.95 to 0.87 comes from the harder new questions.
- Hybrid stays the default: it finds every exact ID and name (1.00); pgvector and Chroma
  miss both certificate numbers (CERT-S003 not found, CERT-S010 5th).
- Version rule holds: "Atlas Components committed monthly capacity" returns v3 first,
  never the superseded v2.
- ms/query differs from the first run on the same code: timings depend on the machine and
  load, so compare them only within one run.

### Still missed by hybrid
| Question | Rank | Why |
|---|---|---|
| Which supplier's quality certificate has run out? | 5 | known: PRO-04 (procedure on expired certificates) comes first |
| What do we do if the message doesn't say which supplier is affected? | not found | PRO-01 is one sentence ("ask for clarification if supplier ... missing") and its title ("Disruption triage") doesn't say it |
| Are users allowed to see negotiated penalty rates? | 2 | PRO-12 (cost/penalties) first, PRO-10 second: still in top 5 |
| Past incidents ... same upstream manufacturer | 3 | all 30 incident reports share one template; the lesson is one line, so HC-024 and HC-014 rank above HC-009 |

### MIN_SIMILARITY
Weakest right question 0.398, strongest off-topic 0.177. 0.30 still sits safely between
them, so it stays (the suggested 0.29 makes no real difference).

