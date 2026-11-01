"""OpenAI-compatible chat client with a recorder.

A provider answer is paid for once: in `record` mode it is stored by the hash of the exact request, and `replay` serves
it back for free. A request that was never recorded fails in `replay`, so tests cannot spend money by accident.
"""
import hashlib
import json
import time
from pathlib import Path

import httpx

from . import config

RECORDINGS = config.ROOT / "tests" / "evals" / "recordings"
SPEND_FILE = config.ROOT / "tests" / "evals" / ".spend.json"
EVAL_BUDGET_USD_PER_DAY = 0.90  # about R$ 5
RETRYABLE = {429, 500, 502, 503, 504}


class RecordingMissing(RuntimeError):
    pass


class EvalBudgetExceeded(RuntimeError):
    pass


def request_key(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def cost_usd(usage: dict) -> float:
    cached = usage.get("prompt_cache_hit_tokens", 0)
    missed = usage.get("prompt_tokens", 0) - cached
    return (cached * config.PRICE_INPUT_CACHED + missed * config.PRICE_INPUT_MISS
            + usage.get("completion_tokens", 0) * config.PRICE_OUTPUT) / 1_000_000


def _post(body: dict) -> dict:
    for attempt in range(3):
        started = time.perf_counter()
        response = httpx.post(f"{config.LLM_BASE_URL}/chat/completions", json=body, timeout=60,
                              headers={"Authorization": f"Bearer {config.LLM_API_KEY}"})
        if response.status_code in RETRYABLE and attempt < 2:
            time.sleep(2 ** attempt)
            continue
        response.raise_for_status()
        data = response.json()
        return {"message": data["choices"][0]["message"], "usage": data["usage"], "model": data.get("model", body["model"]),
                "latency_ms": round((time.perf_counter() - started) * 1000)}
    raise RuntimeError("unreachable: the last attempt either returns or raises")


def _charge_eval(usd: float, spend_file: Path = SPEND_FILE) -> None:
    today = time.strftime("%Y-%m-%d")
    ledger = json.loads(spend_file.read_text()) if spend_file.exists() else {}
    ledger[today] = ledger.get(today, 0) + usd
    spend_file.write_text(json.dumps(ledger))


def _eval_spent_today(spend_file: Path = SPEND_FILE) -> float:
    ledger = json.loads(spend_file.read_text()) if spend_file.exists() else {}
    return ledger.get(time.strftime("%Y-%m-%d"), 0)


def complete(messages: list[dict], tools: list[dict] | None) -> dict:
    body = {"model": config.LLM_MODEL, "messages": messages, "max_tokens": config.MAX_OUTPUT_TOKENS, "temperature": 0.2}
    if tools:
        body["tools"] = tools
    if "deepseek" in config.LLM_BASE_URL:
        body["thinking"] = {"type": "disabled"}  # measured: same accuracy, slower and pricier with it on

    if config.LLM_MODE == "live":
        return _post(body)

    recording = RECORDINGS / f"{request_key(body)}.json"
    if recording.exists():
        return {**json.loads(recording.read_text(encoding="utf-8")), "replayed": True}
    if config.LLM_MODE == "replay":
        raise RecordingMissing(f"no recording for request {recording.stem}: run scripts/evals.py to pay for it once")
    if _eval_spent_today() >= EVAL_BUDGET_USD_PER_DAY:
        raise EvalBudgetExceeded("daily eval budget reached")
    result = _post(body)
    _charge_eval(cost_usd(result["usage"]))
    recording.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
