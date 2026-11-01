"""Behavior evals: pass or fail, one recorded run per case, checked by code.

Default mode is replay, so `pytest` is free and needs no API key. Paying for a new answer goes through scripts/evals.py.
Measured cost of the whole set: see reports/evals.json.
"""
import pytest

from tests.evals.comportamento.cases import CASES
from tests.evals.harness import failures, run_case


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_behavior(case):
    run = run_case(case)
    assert failures(case, run) == [], f"replies: {run.replies}\ncalls: {run.calls}"
