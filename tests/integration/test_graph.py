"""The graph's wiring, with provider responses scripted: these paths depend on code, not on what the model decides."""
import json

import pytest

from emporio import config, graph, llm


def text(content):
    return {"message": {"role": "assistant", "content": content}, "usage": {"prompt_tokens": 100, "completion_tokens": 10}}


def tool_call(name, **arguments):
    call = {"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
    return {"message": {"role": "assistant", "content": "", "tool_calls": [call]}, "usage": {}}


@pytest.fixture
def provider(monkeypatch):
    requests = []

    def script(*responses):
        queue = list(responses)

        def fake(messages, tools):
            requests.append({"messages": messages, "tools": tools})
            return queue.pop(0)

        monkeypatch.setattr(llm, "complete", fake)
        return requests

    return script


def run(thread="t", message="oi", g=None):
    events = list(graph.stream_turn(g or graph.memory_graph(), thread, message))
    return events, events[-1]


def test_supported_reply_passes_untouched(provider):
    provider(tool_call("search_products", query="GD20"), text("Custa R$ 2.199,00."))
    events, final = run()
    assert final["text"] == "Custa R$ 2.199,00."
    assert {"type": "guard", "status": "ok"} in events


def test_invented_price_gets_one_retry_with_the_reason(provider):
    requests = provider(text("Custa R$ 1.935,12."), tool_call("search_products", query="GD20"), text("Custa R$ 2.199,00."))
    events, final = run()
    assert any(e.get("status") == "retry" for e in events)
    assert "1.935,12" in requests[1]["messages"][-1]["content"]
    assert final["text"] == "Custa R$ 2.199,00."


def test_second_failure_cuts_the_sentence_and_keeps_the_rest(provider):
    provider(text("Ótima escolha. Custa R$ 1.935,12."), text("Ótima escolha. Custa R$ 1.111,11."))
    events, final = run()
    assert any(e.get("status") == "cut" for e in events)
    assert "1.111,11" not in final["text"] and final["text"].startswith("Ótima escolha.")
    assert graph.CUT_NOTICE in final["text"]


def test_tool_loop_is_capped_and_the_last_call_has_no_tools(provider):
    requests = provider(*[tool_call("search_policies", query="x") for _ in range(config.MAX_TOOL_ROUNDS)], text("Pronto."))
    _, final = run()
    assert final["text"] == "Pronto."
    assert requests[-1]["tools"] is None


def test_empty_model_reply_becomes_a_safe_message(provider):
    provider(text(""))
    _, final = run()
    assert final["text"] == graph.EMPTY_REPLY


def test_old_tool_results_leave_the_context(provider):
    requests = provider(tool_call("search_products", query="GD20"), text("Custa R$ 2.199,00."), text("Certo!"))
    g = graph.memory_graph()
    run("same", "preço do GD20?", g)
    run("same", "valeu", g)
    last_request = requests[-1]["messages"]
    assert not any(m["role"] == "tool" for m in last_request)
    assert [m["content"] for m in last_request if m["role"] == "assistant"] == ["Custa R$ 2.199,00."]


def test_number_from_a_previous_turn_does_not_count_as_evidence(provider):
    provider(tool_call("search_products", query="GD20"), text("Custa R$ 2.199,00."),
             text("Continua R$ 2.199,00."), text("Continua R$ 2.199,00."))
    g = graph.memory_graph()
    run("same", "preço do GD20?", g)
    events, _ = run("same", "ainda está esse preço?", g)
    assert any(e.get("status") == "cut" for e in events)


def test_verification_survives_across_turns(provider):
    provider(tool_call("get_order", order_id=1, contact="(67) 98432-1098"), text("Entregue."),
             tool_call("get_order", order_id=1), text("Entregue."))
    g = graph.memory_graph()
    run("same", "pedido 1", g)
    events = list(graph.stream_turn(g, "same", "e o status?"))
    output = next(e["output"] for e in events if e["type"] == "tool_end")
    assert output["status"] == "ok"


def test_conversations_do_not_share_verification(provider):
    provider(tool_call("get_order", order_id=1, contact="(67) 98432-1098"), text("Entregue."),
             tool_call("get_order", order_id=1), text("Preciso do contato."))
    g = graph.memory_graph()
    run("customer-a", "pedido 1", g)
    events = list(graph.stream_turn(g, "customer-b", "pedido 1"))
    assert next(e["output"] for e in events if e["type"] == "tool_end")["status"] == "needs_contact"
