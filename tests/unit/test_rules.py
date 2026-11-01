from datetime import date, timedelta

import pytest

from emporio import rules

TODAY = date(2026, 3, 25)


@pytest.mark.parametrize("amount, expected", [
    (49.99, 0),     # 1x is already under the R$ 50 minimum
    (50, 1),
    (150, 3),       # 3x = 50 ok; 4x needs R$ 80
    (320, 4),       # 4x = 80 exactly
    (479, 5),       # 5x = 95.80; 6x = 79.83 fails the R$ 80 minimum
    (480, 6),
    (699, 6),       # 7x = 99.86 fails the R$ 100 minimum
    (700, 7),
    (1200, 12),
    (99999, 12),
])
def test_installment_limits_follow_section_3_1(amount, expected):
    assert rules.max_installments(amount) == expected


def test_pix_discount_does_not_stack_with_promotion():
    assert rules.pix_price(1000, on_promotion=False) == 950
    assert rules.pix_price(1000, on_promotion=True) is None


def test_combined_payment_only_above_2000():
    assert not rules.payment_options(2000, False)["can_combine_payment_methods"]
    assert rules.payment_options(2000.01, False)["can_combine_payment_methods"]


def request(reason, received_days_ago=3, purchased_days_ago=10, status="delivered", remote=True, estimate=False):
    return rules.ReturnRequest(reason=reason, status=status, order_date=TODAY - timedelta(days=purchased_days_ago),
                               received=TODAY - timedelta(days=received_days_ago), received_is_estimate=estimate,
                               bought_remotely=remote, today=TODAY)


@pytest.mark.parametrize("days, decision", [(7, "allowed"), (8, "denied")])
def test_regret_window_is_seven_calendar_days_from_receipt(days, decision):
    assert rules.return_decision(request("regret", received_days_ago=days))["decision"] == decision


def test_regret_does_not_cover_in_store_purchases():
    result = rules.return_decision(request("regret", remote=False))
    assert result["decision"] == "denied" and "§4.3" in result["explanation"]


@pytest.mark.parametrize("days, decision", [(7, "allowed"), (8, "denied")])
def test_preference_exchange_window(days, decision):
    assert rules.return_decision(request("preference", received_days_ago=days))["decision"] == decision


@pytest.mark.parametrize("purchased, received, decision, section", [
    (30, 20, "allowed", "§4.2"),                 # store exchange counts from the purchase
    (31, 20, "needs_human", "§8.1"),             # conflict in the manual: legal warranty still applies
    (120, 90, "needs_human", "§8.1"),            # legal warranty counts from receipt
    (120, 91, "manufacturer_warranty", "§4.2"),
])
def test_defect_paths(purchased, received, decision, section):
    result = rules.return_decision(request("defect", received_days_ago=received, purchased_days_ago=purchased))
    assert (result["decision"], result["policy_section"]) == (decision, section)


@pytest.mark.parametrize("status, decision", [("cancelled", "not_applicable"), ("pending", "needs_human"),
                                              ("confirmed", "needs_human"), ("shipped", "needs_human")])
def test_orders_not_delivered_never_get_a_deadline(status, decision):
    result = rules.return_decision(request("regret", status=status))
    assert result["decision"] == decision and "deadline" not in result


def test_estimated_receipt_is_flagged_so_the_agent_can_confirm_it():
    assert rules.return_decision(request("regret", estimate=True))["received_date_is_estimate"] is True
