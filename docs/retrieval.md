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