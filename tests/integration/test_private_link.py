"""The public address stays closed: every route needs the private link, except the health check."""
import pytest
from fastapi.testclient import TestClient

from emporio import app as web, config

TOKEN = "test-token-123"
CHAT = {"session_id": "session-private", "message": "oi"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_TOKEN", TOKEN)
    return TestClient(web.app, base_url="https://testserver", follow_redirects=False)


@pytest.mark.parametrize("path", ["/", "/static/app.js", "/api/quality", "/api/history/session-private", "/?k=wrong", "/?k="])
def test_without_the_link_nothing_opens(client, path):
    assert client.get(path).status_code == 403


def test_the_agent_cannot_be_called_without_the_link(client, monkeypatch):
    monkeypatch.setattr(web.db, "spent_today", lambda: pytest.fail("reached the route"))
    assert client.post("/api/chat", json=CHAT).status_code == 403


def test_the_link_opens_and_removes_the_token_from_the_address(client):
    response = client.get(f"/?k={TOKEN}")
    assert response.status_code == 303 and response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and TOKEN not in cookie
    assert client.get("/").status_code == 200
    assert client.get(f"/?k={TOKEN}").status_code == 303  # opening the link again also clears the address bar


def test_a_forged_cookie_does_not_open(client):
    client.cookies.set(web.ACCESS_COOKIE, TOKEN)
    assert client.get("/").status_code == 403


def test_health_stays_open_for_the_server_check(client):
    assert client.get("/health").status_code == 200


def test_local_run_without_a_token_stays_open(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_TOKEN", "")
    assert TestClient(web.app).get("/").status_code == 200
