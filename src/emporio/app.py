"""HTTP API and static UI. One process: the graph, rate limit and budget all live here."""
import hashlib
import hmac
import json
import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterator, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db
from .graph import persistent_graph, stream_turn

WEB = config.ROOT / "web"
REPORT = config.ROOT / "reports" / "evals.json"
ACCESS_COOKIE = "emporio_access"
ACCESS_DAYS = 30
PRIVATE_PAGE = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                "<title>Private demo</title><body style=\"margin:0;display:grid;place-items:center;height:100vh;"
                'background:#0e1014;color:#cdc9c1;font-family:system-ui,sans-serif;text-align:center">'
                "<p>This demo opens only through its private link.<br>Esta demonstração só abre pelo link privado.</p></body></html>")
SESSION_ID = re.compile(r"^[a-zA-Z0-9-]{8,64}$")
BUSY_MESSAGE = {
    "pt": "Estou com muitas conversas agora. Tente de novo em alguns minutos ou fale com a loja pelo (67) 3341-4444.",
    "en": "I'm handling many conversations right now. Please try again in a few minutes or call the store at (67) 3341-4444.",
}
ERROR_MESSAGE = {
    "pt": "Tive um problema para responder agora. Pode tentar de novo? Se preferir, fale com a loja pelo (67) 3341-4444.",
    "en": "I had a problem answering just now. Could you try again? You can also call the store at (67) 3341-4444.",
}

app = FastAPI(title="Empório da Música", docs_url=None, redoc_url=None)
graph = persistent_graph()
_recent: dict[str, deque] = defaultdict(deque)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    language: Literal["pt", "en"] = "pt"


def _access_pass() -> str:
    """The cookie holds a hash, so the browser never keeps the link's token itself."""
    return hashlib.sha256(config.ACCESS_TOKEN.encode()).hexdigest()


@app.middleware("http")
async def private_link(request: Request, call_next):
    """Only people who received the link get in. It sets a cookie and leaves the address bar, so the token is not left there."""
    if not config.ACCESS_TOKEN or request.url.path == "/health":
        return await call_next(request)
    if hmac.compare_digest(request.query_params.get("k", ""), config.ACCESS_TOKEN):
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(ACCESS_COOKIE, _access_pass(), max_age=ACCESS_DAYS * 86400, httponly=True, secure=True,
                            samesite="lax")
        return response
    if hmac.compare_digest(request.cookies.get(ACCESS_COOKIE, ""), _access_pass()):
        return await call_next(request)
    return HTMLResponse(PRIVATE_PAGE, status_code=403)


def _client_ip(request: Request) -> str:
    """The proxy appends the real address last. Earlier entries come from the client and can be forged."""
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[-1].strip() or (request.client.host if request.client else "unknown")


def _over_rate_limit(ip: str) -> bool:
    now = time.monotonic()
    window = _recent[ip]
    while window and now - window[0] > config.RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= config.RATE_LIMIT_MESSAGES:
        return True
    window.append(now)
    return False


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _events(session_id: str, message: str, language: str) -> Iterator[str]:
    try:
        for event in stream_turn(graph, session_id, message, language=language):
            yield _sse(event)
    except Exception as error:  # the customer gets a way out; the reason goes to the log
        print(f"turn failed: {type(error).__name__}: {error}", flush=True)
        yield _sse({"type": "final", "text": ERROR_MESSAGE[language], "stats": None})


@app.post("/api/chat")
def chat(body: ChatRequest, request: Request) -> StreamingResponse:
    if not SESSION_ID.match(body.session_id):
        raise HTTPException(422, "invalid session")
    message = body.message.strip()
    if not message or len(message) > config.MAX_MESSAGE_CHARS:
        raise HTTPException(422, f"message must have 1 to {config.MAX_MESSAGE_CHARS} characters")
    if _over_rate_limit(_client_ip(request)) or db.spent_today() >= config.DAILY_BUDGET_USD:
        refusal = iter([_sse({"type": "final", "text": BUSY_MESSAGE[body.language], "stats": None})])
        return StreamingResponse(refusal, media_type="text/event-stream")
    return StreamingResponse(_events(body.session_id, message, body.language), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/history/{session_id}")
def history(session_id: str) -> dict:
    if not SESSION_ID.match(session_id):
        raise HTTPException(422, "invalid session")
    state = graph.get_state({"configurable": {"thread_id": session_id}}).values
    said = [m for m in state.get("messages", []) if m["role"] == "user" or m.get("final")]
    return {"messages": [{"role": m["role"], "content": m["content"]} for m in said]}


@app.get("/api/quality")
def quality() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": os.environ.get("APP_VERSION", "dev"), "model": config.LLM_MODEL}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=Path(WEB)), name="static")
