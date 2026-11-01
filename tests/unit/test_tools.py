import json
from datetime import datetime

import pytest

from emporio import rules, tools
from emporio.config import STORE_TZ

PEDRO = "(67) 98432-1098"


def call(name, ctx=None, **arguments):
    return tools.execute(name, json.dumps(arguments), {} if ctx is None else ctx)


def test_order_without_contact_reveals_nothing():
    assert call("get_order", order_id=1) == {"status": "needs_contact", "instruction": "Peça o telefone ou e-mail usado na compra."}


def test_unknown_order_and_wrong_contact_are_indistinguishable():
    assert call("get_order", order_id=999, contact=PEDRO) == call("get_order", order_id=1, contact="(67) 90000-0000")


def test_contact_of_another_customer_does_not_open_the_order():
    assert call("get_order", order_id=2, contact=PEDRO)["status"] == "not_verified"


def test_verified_order_stays_open_for_the_conversation():
    ctx = {}
    assert call("get_order", ctx, order_id=1, contact=PEDRO)["status"] == "ok"
    assert call("get_order", ctx, order_id=1)["status"] == "ok"


def test_verification_of_one_order_does_not_open_another():
    ctx = {}
    call("get_order", ctx, order_id=1, contact=PEDRO)
    assert call("get_order", ctx, order_id=2)["status"] == "needs_contact"


def test_three_wrong_contacts_lock_the_conversation():
    ctx = {}
    for attempt in range(3):
        assert call("get_order", ctx, order_id=attempt + 1, contact="(67) 90000-0000")["status"] == "not_verified"
    assert call("get_order", ctx, order_id=1, contact=PEDRO)["status"] == "locked"


def test_return_check_is_behind_the_same_verification():
    assert call("check_return", order_id=1, reason="regret", contact="errado@x.com")["status"] == "not_verified"


def test_return_check_brings_the_name_so_the_reply_has_no_placeholder():
    assert call("check_return", order_id=1, reason="regret", contact=PEDRO)["customer_first_name"] == "Pedro"


def test_invalid_model_output_returns_an_error_instead_of_crashing():
    assert "error" in tools.execute("get_order", "{not json", {})
    assert "error" in tools.execute("get_order", '{"wrong_argument": 1}', {})
    assert "error" in tools.execute("drop_table", "{}", {})
    assert "error" in tools.execute("check_return", '{"order_id": 1, "reason": "regret", "contact": "%s", "received_date": "ontem"}' % PEDRO, {})


def test_order_id_as_text_is_accepted():
    assert tools.execute("get_order", json.dumps({"order_id": "#1", "contact": PEDRO}), {})["status"] == "ok"


def test_handoff_returns_a_protocol_and_the_manual_deadline():
    result = call("escalate_to_human", {"thread_id": "t"}, reason="complaint", summary="cliente insatisfeito")
    assert result["protocol"].startswith("EM-") and "24 horas úteis" in result["response_time"]


def test_policy_tool_returns_sections():
    assert "1.2" in [s["section"] for s in call("search_policies", query="qual o endereço?")["sections"]]


@pytest.mark.parametrize("moment, expected", [
    (datetime(2026, 3, 25, 10, 0), "aberta até as 18h"),   # Wednesday
    (datetime(2026, 3, 25, 18, 0), "fechada e reabre amanhã às 9h"),
    (datetime(2026, 3, 28, 12, 59), "aberta até as 13h"),  # Saturday
    (datetime(2026, 3, 28, 13, 0), "fechada e reabre segunda-feira às 9h"),
    (datetime(2026, 3, 29, 15, 0), "fechada e reabre amanhã às 9h"),  # Sunday
    (datetime(2026, 3, 25, 7, 0), "fechada e reabre hoje às 9h"),
])
def test_store_status_uses_the_clock(moment, expected):
    assert expected in rules.store_status(moment.replace(tzinfo=STORE_TZ))
