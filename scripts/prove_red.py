"""A test that cannot fail proves nothing, so this breaks the code on purpose and expects the suite to turn red.

    uv run python scripts/prove_red.py

Each mutation runs on a temporary copy. It uses only the free tests and writes reports/mutations.json.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = [
    ("regret window of 8 days instead of 7", "src/emporio/rules.py", "REGRET_DAYS = 7", "REGRET_DAYS = 8"),
    ("PIX discount stacks with promotion", "src/emporio/rules.py", "return None if on_promotion else round", "return round"),
    ("installment minimums ignored", "src/emporio/rules.py", "amount / n >= _tier_minimum(n)", "True"),
    ("expired promotions change the price", "src/emporio/store.py", 'if row["is_active"] == "1":', "if True:"),
    ("browsing shows unavailable products", "src/emporio/store.py", "        if not query:\n            found = [p for p in found if self.availability(p) == AVAILABLE]", "        pass"),
    ("coming soon sold because it has stock", "src/emporio/store.py", 'if product["status"] == "coming_soon":', "if False:"),
    ("order opens with any contact", "src/emporio/tools.py", "if store().contact_matches(order_id, contact):", "if True:"),
    ("no lock after wrong contacts", "src/emporio/tools.py", 'if ctx.get("failed_checks", 0) >= MAX_FAILED_CHECKS:', "if False:"),
    ("full name reaches the model", "src/emporio/store.py", '["name"].split()[0]', '["name"]'),
    ("guard lets every number through", "src/emporio/guard.py", "return numbers + emails + _PLACEHOLDER.findall(reply)", "return []"),
    ("guard retry removed", "src/emporio/graph.py", 'if not state["retried"]:', "if False:"),
    ("old tool results stay in context", "src/emporio/graph.py", 'if m["role"] == "user" or m.get("final")', "if True"),
    ("tool loop has no cap", "src/emporio/graph.py", 'offer_tools = state["rounds"] < config.MAX_TOOL_ROUNDS', "offer_tools = True"),
    ("rate limit disabled", "src/emporio/app.py", "if len(window) >= config.RATE_LIMIT_MESSAGES:", "if False:"),
    ("daily budget disabled", "src/emporio/app.py", " or db.spent_today() >= config.DAILY_BUDGET_USD", ""),
    ("WhatsApp conflict not annotated", "src/emporio/policies.py", '    "7": "Nota: o WhatsApp oficial é o (67) 3341-4444, o mesmo da seção 1.2.",\n', ""),
]


def run_free_tests(folder: Path) -> bool:
    environment = {**os.environ, "LLM_MODE": "replay"}
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/unit", "tests/integration", "-x", "-q", "--no-header",
                             "-p", "no:cacheprovider"], cwd=folder, env=environment, capture_output=True, text=True)
    return result.returncode == 0


def fresh_copy(folder: str) -> Path:
    copy = Path(folder) / "repo"
    shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".venv", ".git", "var", "recordings", "__pycache__"))
    return copy


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:  # control: if the untouched copy fails, every "red" below means nothing
        if not run_free_tests(fresh_copy(folder)):
            raise SystemExit("control failed: the suite is red without any mutation")
    print("GREEN control, no mutation")
    results = []
    for title, file, original, broken in MUTATIONS:
        with tempfile.TemporaryDirectory() as folder:
            copy = fresh_copy(folder)
            target = copy / file
            source = target.read_text(encoding="utf-8").replace("\r\n", "\n")
            if original not in source:
                raise SystemExit(f"mutation no longer applies: {title}")
            target.write_text(source.replace(original, broken), encoding="utf-8")
            caught = not run_free_tests(copy)
        results.append({"mutation": title, "caught": caught})
        print(("RED   " if caught else "MISSED ") + title)
    caught = sum(r["caught"] for r in results)
    print(f"\n{caught}/{len(results)} mutations caught")
    (ROOT / "reports" / "mutations.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(0 if caught == len(results) else 1)


if __name__ == "__main__":
    main()
