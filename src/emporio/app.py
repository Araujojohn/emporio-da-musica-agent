"""HTTP API and static UI. One process: the graph, rate limit and budget all live here."""
import json
import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterator, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db
from .graph import persistent_graph, stream_turn

WEB = config.ROOT / "web"
REPORT = config.ROOT / "reports" / "evals.json"
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
