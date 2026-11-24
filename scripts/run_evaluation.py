"""Run the trainer's 105 evaluation cases and score them per category. OWNER: role 1.

    uv run python scripts/run_evaluation.py --local              # scores printed here
    uv run python scripts/run_evaluation.py --local --no-judge   # no LLM-as-judge (faster)
    uv run python scripts/run_evaluation.py --local --category ambiguity
    uv run python scripts/run_evaluation.py                      # upload the dataset (once) and
                                                                 # run an experiment in LangSmith
Needs the .env (Azure; LangSmith for the online mode). See src/supplyguard_ai/evaluation.py.
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

if "--local" in sys.argv:  # before supplyguard_ai loads .env: keep local runs out of LangSmith
    import os

    os.environ["LANGSMITH_TRACING"] = "false"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from supplyguard_ai.evaluation import Runner, load_cases, run_case, score  # noqa: E402

DATASET_NAME = "supplyguard-eval-105"


def run_locally(category: str | None, use_judge: bool) -> None:
    runner = Runner()
    totals, counts = defaultdict(float), defaultdict(int)
    for case in load_cases():
        if category and case["category"] != category:
            continue
        try:
            result = score(case, run_case(case, runner), use_judge)
        except Exception as error:  # one broken case must not stop the run
            result = {"key": case["category"], "score": 0, "comment": f"ERROR {type(error).__name__}: {error}"}
        totals[result["key"]] += result["score"]
        counts[result["key"]] += 1
        mark = "ok  " if result["score"] == 1 else "FAIL"
        print(f"{mark} {case['id']} {case['category']:<26} {result['comment'][:110]}")
    print("\nScore per category:")
    for key in counts:
        print(f"  {key:<26} {totals[key] / counts[key]:.2f}  ({counts[key]} cases)")
    overall = sum(totals.values()) / max(sum(counts.values()), 1)
    print(f"  {'OVERALL':<26} {overall:.2f}  ({sum(counts.values())} cases)")


def run_in_langsmith(use_judge: bool) -> None:
    from langsmith import Client

    client = Client()
    if not client.has_dataset(dataset_name=DATASET_NAME):
        dataset = client.create_dataset(DATASET_NAME, description="The trainer's 105 SupplyGuard cases.")
        client.create_examples(dataset_id=dataset.id, examples=[
            {"inputs": {"case": c}, "outputs": c["expected"], "metadata": {"id": c["id"], "category": c["category"]}}
            for c in load_cases()])
    runner = Runner()

    def target(inputs: dict) -> dict:
        return run_case(inputs["case"], runner)

    def evaluator(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        return score(inputs["case"], outputs, use_judge)

    results = client.evaluate(target, data=DATASET_NAME, evaluators=[evaluator],
                              experiment_prefix="supplyguard", max_concurrency=1)
    print(f"Done: LangSmith -> Datasets & Experiments -> {DATASET_NAME} -> {results.experiment_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the 105 evaluation cases.")
    parser.add_argument("--local", action="store_true", help="print scores here, send nothing to LangSmith")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM-as-judge")
    parser.add_argument("--category", help="run only one category")
    args = parser.parse_args()
    if args.local:
        run_locally(args.category, not args.no_judge)
    else:
        run_in_langsmith(not args.no_judge)


if __name__ == "__main__":
    main()
