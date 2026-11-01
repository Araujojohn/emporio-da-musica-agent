"""The real FastAPI app, with the provider scripted: routes, limits and streaming are code, so they are tested for free."""
import json

import pytest
from fastapi.testclient import TestClient

from emporio import app as web, config, db, llm


@pytest.fixture
def client(monkeypatch):
    web._recent.clear()
    monkeypatch.setattr(llm, "complete", lambda messages, tools: {
        "message": {"role": "assistant", "content": "Oi! Como posso ajudar?"}, "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    return TestClient(web.app)


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def post(client, message="oi", session="session-1234"):
    return client.post("/api/chat", json={"session_id": session, "message": message})


def test_chat_streams_steps_and_ends_with_the_final_event(client):
    received = events(post(client))
    assert received[0]["type"] == "thinking"
    assert received[-1]["type"] == "final" and received[-1]["text"] == "Oi! Como posso ajudar?"
    assert received[-1]["stats"]["llm_calls"] == 1


def test_history_survives_for_the_session(client):
    post(client, session="session-history")
    said = client.get("/api/history/session-history").json()["messages"]
    assert [m["role"] for m in said] == ["user", "assistant"]


def test_a_new_session_starts_empty(client):
    assert client.get("/api/history/session-new-one").json() == {"messages": []}


@pytest.mark.parametrize("message", ["", "   ", "x" * (config.MAX_MESSAGE_CHARS + 1)])
def test_message_size_is_limited(client, message):
    assert post(client, message).status_code == 422


def test_invalid_session_is_rejected(client):
    assert post(client, session="../../etc").status_code == 422


def test_rate_limit_answers_politely_without_calling_the_model(client, monkeypatch):
    for _ in range(config.RATE_LIMIT_MESSAGES):
        post(client)
    monkeypatch.setattr(llm, "complete", lambda *_: pytest.fail("model must not be called"))
    assert events(post(client))[-1]["text"] == web.BUSY_MESSAGE["pt"]


def test_forged_forwarded_header_does_not_escape_the_rate_limit(client, monkeypatch):
    for i in range(config.RATE_LIMIT_MESSAGES):
        client.post("/api/chat", json={"session_id": "session-1234", "message": "oi"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.9"})
    response = client.post("/api/chat", json={"session_id": "session-1234", "message": "oi"},
                           headers={"X-Forwarded-For": "10.9.9.9, 203.0.113.9"})
    assert events(response)[-1]["text"] == web.BUSY_MESSAGE["pt"]


def test_daily_budget_stops_the_model(client, monkeypatch):
    monkeypatch.setattr(db, "spent_today", lambda: config.DAILY_BUDGET_USD)
    monkeypatch.setattr(llm, "complete", lambda *_: pytest.fail("model must not be called"))
    assert events(post(client))[-1]["text"] == web.BUSY_MESSAGE["pt"]


def test_provider_failure_reaches_the_customer_as_a_way_out(client, monkeypatch):
    def broken(*_):
        raise TimeoutError("provider down")

    monkeypatch.setattr(llm, "complete", broken)
    assert events(post(client, session="session-broken"))[-1]["text"] == web.ERROR_MESSAGE["pt"]


def test_spend_is_recorded_per_day(client):
    before = db.spent_today()
    post(client, session="session-spend")
    assert db.spent_today() > before


def test_health_and_page_are_served(client):
    assert client.get("/health").json()["status"] == "ok"
    assert "Empório da Música" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
