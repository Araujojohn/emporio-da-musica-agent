"""Tests never spend by accident: replay is the default and only scripts/evals.py turns on `record`."""
import os
import tempfile

os.environ.setdefault("LLM_MODE", "replay")
os.environ.setdefault("LLM_API_KEY", "unused-in-replay")
os.environ.setdefault("FIXED_NOW", "2026-03-25T10:30:00")  # a Wednesday, store open
os.environ["STATE_DIR"] = tempfile.mkdtemp(prefix="emporio-tests-")
