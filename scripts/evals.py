"""The only way to pay for model answers.

    uv run python scripts/evals.py behavior [--only CASE_ID]
    uv run python scripts/evals.py performance

Each request is recorded by its hash, so only what changed is paid for and an identical re-run costs nothing. A daily
budget in llm.py stops the run. The report goes to reports/evals.json, which the UI reads.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
os.environ["LLM_MODE"] = os.environ.get("LLM_MODE_OVERRIDE", "record")
os.environ.setdefault("FIXED_NOW", "2026-03-25T10:30:00")
os.environ["STATE_DIR"] = str(ROOT / "var" / "evals")

from emporio import config, llm  # noqa: E402
from tests.evals.comportamento.cases import CASES as BEHAVIOR  # noqa: E402
from tests.evals.desempenho.cases import CASES as PERFORMANCE  # noqa: E402
from tests.evals.harness import failures, run_case  # noqa: E402

REPORT = ROOT / "reports" / "evals.json"


def evaluate(cases: list) -> dict:
    rows = []
    for case in cases:
        run = run_case(case)
        problems = failures(case, run)
        cost = sum(s["cost_usd"] for s in run.stats)
        latency = sum(s["llm_ms"] for s in run.stats)
        rows.append({"id": case.id, "passed": not problems, "problems": problems, "reply": run.replies[-1],
                     "tools": [name for name, _ in run.calls], "cost_usd": round(cost, 6), "latency_ms": latency,
                     "model": run.stats[-1]["model"]})
        print(("PASS " if not problems else "FAIL ") + case.id + ("" if not problems else f"  {problems}"))
    passed = sum(r["passed"] for r in rows)
    latencies = sorted(r["latency_ms"] for r in rows)
    return {"cases": len(rows), "passed": passed, "pass_rate": round(passed / len(rows), 4),
            "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 5),
            "cost_per_case_usd": round(sum(r["cost_usd"] for r in rows) / len(rows), 6),
            "median_latency_ms": latencies[len(latencies) // 2], "p95_latency_ms": latencies[int(len(latencies) * .95)],
            "model": rows[-1]["model"], "date": time.strftime("%Y-%m-%d"), "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=["behavior", "performance"])
    parser.add_argument("--only")
    args = parser.parse_args()
    cases = BEHAVIOR if args.suite == "behavior" else PERFORMANCE
    if args.only:
        cases = [c for c in cases if c.id == args.only]
    before = llm._eval_spent_today()
    result = evaluate(cases)
    spent = llm._eval_spent_today() - before
    print(f"\n{result['passed']}/{result['cases']} passed · paid today in this run: US$ {spent:.4f} · model {config.LLM_MODEL}")
    if not args.only:
        REPORT.parent.mkdir(exist_ok=True)
        report = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
        report[args.suite] = result
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(0 if result["passed"] == result["cases"] else 1)


if __name__ == "__main__":
    main()
