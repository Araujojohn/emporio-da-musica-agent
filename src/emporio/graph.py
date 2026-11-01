"""The agent: model ⇄ tools → guard → customer.

    begin → model ─┬→ tools → model (up to MAX_TOOL_ROUNDS)
                   └→ guard ─┬→ model (one retry when a number has no source)
                             └→ END
"""
import json
import time
from operator import add
from pathlib import Path
from typing import Annotated, Iterator, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from . import config, db, guard, llm, rules, tools

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")
CUT_NOTICE = "Prefiro confirmar esse detalhe com a equipe para não te passar nada errado."
EMPTY_REPLY = "Desculpa, não consegui responder agora. Pode tentar de novo? Se preferir, fale com a equipe pelo (67) 3341-4444."
RETRY_NOTE = ("Revisão interna: estes dados da sua resposta não vieram de nenhuma ferramenta desta rodada: {items}. "
              "Consulte a ferramenta certa ou reescreva sem eles.")


class State(TypedDict, total=False):
    messages: Annotated[list[dict], add]
    turn_start: int
    rounds: int
    retried: bool
    ctx: dict
    stats: dict


def _for_model(message: dict) -> dict:
    return {k: v for k, v in message.items() if k != "final"}


def build_request(state: State) -> list[dict]:
    """Past turns keep only what was said. Old tool results stay out, so stock and prices are always read again."""
    messages = state["messages"]
    start = state["turn_start"]
    history = [m for m in messages[:start] if m["role"] == "user" or m.get("final")][-config.HISTORY_MESSAGES:]
    clock = {"role": "system", "content": rules.store_status(config.now())}
    return [{"role": "system", "content": SYSTEM_PROMPT}, *map(_for_model, history), clock,
            *map(_for_model, messages[start:])]


def begin(state: State) -> dict:
    return {"turn_start": len(state["messages"]) - 1, "rounds": 0, "retried": False, "ctx": state.get("ctx") or {},
            "stats": {"llm_calls": 0, "prompt_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                      "llm_ms": 0, "model": ""}}


def model(state: State) -> dict:
    get_stream_writer()({"type": "thinking"})
    offer_tools = state["rounds"] < config.MAX_TOOL_ROUNDS
    result = llm.complete(build_request(state), tools.SCHEMAS if offer_tools else None)
    usage = result["usage"]
    stats = dict(state["stats"])
    stats["llm_calls"] += 1
    stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
    stats["cached_tokens"] += usage.get("prompt_cache_hit_tokens", 0)
    stats["output_tokens"] += usage.get("completion_tokens", 0)
    stats["cost_usd"] += llm.cost_usd(usage)
    stats["llm_ms"] += result.get("latency_ms", 0)
    stats["model"] = result.get("model", "")
    if not result.get("replayed"):
        db.add_spend(llm.cost_usd(usage))
    message = {k: v for k, v in result["message"].items() if k in ("role", "content", "tool_calls") and v}
    return {"messages": [{"role": "assistant", "content": "", **message}], "stats": stats}


def after_model(state: State) -> str:
    return "tools" if state["messages"][-1].get("tool_calls") else "guard"


def run_tools(state: State) -> dict:
    write = get_stream_writer()
    ctx = dict(state["ctx"], thread_id=state["ctx"].get("thread_id", ""))
    results = []
    for call in state["messages"][-1]["tool_calls"]:
        name, arguments = call["function"]["name"], call["function"]["arguments"]
        write({"type": "tool_start", "id": call["id"], "name": name, "arguments": arguments})
        started = time.perf_counter()
        output = tools.execute(name, arguments, ctx)
        write({"type": "tool_end", "id": call["id"], "name": name, "output": output,
               "ms": round((time.perf_counter() - started) * 1000)})
        results.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(output, ensure_ascii=False)})
    return {"messages": results, "rounds": state["rounds"] + 1, "ctx": ctx}


def evidence(state: State) -> str:
    """Everything the reply may quote: this turn's tool results, the customer's message and the clock."""
    turn = state["messages"][state["turn_start"]:]
    sources = [m["content"] for m in turn if m["role"] in ("tool", "user")]
    return " ".join([*sources, rules.store_status(config.now())])


def check(state: State) -> dict:
    write = get_stream_writer()
    reply = state["messages"][-1].get("content", "").strip()
    problems = guard.unverified(reply, evidence(state))
    if not problems:
        write({"type": "guard", "status": "ok"})
        return {"messages": [{"role": "assistant", "content": reply or EMPTY_REPLY, "final": True}]}
    if not state["retried"]:
        write({"type": "guard", "status": "retry", "items": problems})
        note = RETRY_NOTE.format(items=", ".join(problems))
        return {"messages": [{"role": "system", "content": note}], "retried": True}
    write({"type": "guard", "status": "cut", "items": problems})
    remaining = guard.cut_sentences(reply, problems)
    final = f"{remaining}\n\n{CUT_NOTICE}".strip()
    return {"messages": [{"role": "assistant", "content": final, "final": True}]}


def after_check(state: State) -> str:
    return "end" if state["messages"][-1].get("final") else "model"


def build(checkpointer):
    graph = StateGraph(State)
    graph.add_node("begin", begin)
    graph.add_node("model", model)
    graph.add_node("tools", run_tools)
    graph.add_node("guard", check)
    graph.add_edge(START, "begin")
    graph.add_edge("begin", "model")
    graph.add_conditional_edges("model", after_model, {"tools": "tools", "guard": "guard"})
    graph.add_edge("tools", "model")
    graph.add_conditional_edges("guard", after_check, {"end": END, "model": "model"})
    return graph.compile(checkpointer=checkpointer)


def persistent_graph():
    return build(SqliteSaver(db.connect()))


def memory_graph():
    return build(MemorySaver())


def stream_turn(graph, thread_id: str, text: str, history: list[dict] | None = None) -> Iterator[dict]:
    """Runs one customer message, yielding each step as it happens and then the `final` event."""
    conversation = {"configurable": {"thread_id": thread_id}}
    known = graph.get_state(conversation).values.get("ctx") or {"thread_id": thread_id}
    turn = {"messages": [*(history or []), {"role": "user", "content": text}], "ctx": known}
    started = time.perf_counter()
    yield from graph.stream(turn, conversation, stream_mode="custom")
    state = graph.get_state(conversation).values
    yield {"type": "final", "text": state["messages"][-1]["content"], "stats": {
        **state["stats"], "total_ms": round((time.perf_counter() - started) * 1000)}}
