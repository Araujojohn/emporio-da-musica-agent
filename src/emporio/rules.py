"""Business rules from the store manual, as code.

Anything with a number or a deadline lives here, never in the prompt: the model chooses what to ask, this module
answers. Each function cites the manual section it implements.
"""
from dataclasses import dataclass
from datetime import date, timedelta

PIX_DISCOUNT_PERCENT = 5
INSTALLMENT_TIERS = ((3, 50.0), (6, 80.0), (12, 100.0))  # §3.1: (up to N installments, minimum installment)
REGRET_DAYS = 7  # §4.1
DEFECT_EXCHANGE_DAYS = 30  # §4.2
PREFERENCE_DAYS = 7  # §4.3
LEGAL_WARRANTY_DAYS = 90  # §8.1


def promo_price(price: float, discount_percent: float) -> float:
    return round(price * (1 - discount_percent / 100), 2)


def pix_price(price: float, on_promotion: bool) -> float | None:
    """§3 gives 5% off on PIX; §6.2 says it does not stack with a promotion."""
    return None if on_promotion else round(price * (1 - PIX_DISCOUNT_PERCENT / 100), 2)


def max_installments(amount: float) -> int:
    """Largest number of interest-free installments allowed by §3.1. Zero when even 1x falls under the minimum."""
    return max((n for n in range(1, 13) if amount / n >= _tier_minimum(n)), default=0)


def _tier_minimum(installments: int) -> float:
    return next(minimum for limit, minimum in INSTALLMENT_TIERS if installments <= limit)


def payment_options(amount: float, on_promotion: bool) -> dict:
    biggest = max_installments(amount)
    return {
        "amount": amount,
        "pix": pix_price(amount, on_promotion),
        "pix_note": "PIX discount does not apply to promotional prices (§6.2)" if on_promotion else "5% off on PIX (§3)",
        "debit_or_boleto": amount,
        "credit_installments": [{"times": n, "value": round(amount / n, 2)} for n in range(1, biggest + 1)],
        "max_interest_free_installments": biggest,
        "can_combine_payment_methods": amount > 2000,  # §3.1
    }


@dataclass(frozen=True)
class ReturnRequest:
    reason: str  # regret | defect | preference
    status: str
    order_date: date
    received: date | None
    received_is_estimate: bool
    bought_remotely: bool
    today: date


def return_decision(r: ReturnRequest) -> dict:
    """Applies §4 and §8.1. Exclusions (§4.4) depend on facts the data does not have, so they are returned as a check."""
    if r.status == "cancelled":
        return _decision("not_applicable", "§4", "The order was cancelled, so there is nothing to return.")
    if r.status in ("pending", "confirmed"):
        return _decision("needs_human", "§4", "The order has not shipped yet: the team must cancel it.")
    if r.status == "shipped":
        return _decision("needs_human", "§4", "The order is in transit: the team must intercept or receive it back.")

    days_since_received = (r.today - r.received).days
    days_since_purchase = (r.today - r.order_date).days
    facts = {"days_since_received": days_since_received, "days_since_purchase": days_since_purchase,
             "received_date": r.received.isoformat(), "received_date_is_estimate": r.received_is_estimate}
    deadline = lambda start, days: {"deadline": (start + timedelta(days=days)).isoformat()}

    if r.reason == "regret":
        if not r.bought_remotely:
            return _decision("denied", "§4.1", "Right of regret covers online purchases only; this was bought in store. "
                             "A preference exchange (§4.3) may still apply.", facts)
        if days_since_received <= REGRET_DAYS:
            return _decision("allowed", "§4.1", "Unused, in original packaging, with all accessories and manuals. Refund "
                             "by the original payment method within 10 business days. The store pays return shipping.",
                             {**facts, **deadline(r.received, REGRET_DAYS)})
        return _decision("denied", "§4.1", f"The {REGRET_DAYS}-day regret window has passed.",
                         {**facts, **deadline(r.received, REGRET_DAYS)})

    if r.reason == "preference":
        if days_since_received <= PREFERENCE_DAYS:
            return _decision("allowed", "§4.3", "Perfect condition and original packaging, subject to stock of the "
                             "desired product. Price differences are charged or refunded.",
                             {**facts, **deadline(r.received, PREFERENCE_DAYS)})
        return _decision("denied", "§4.3", f"The {PREFERENCE_DAYS}-day exchange window has passed.",
                         {**facts, **deadline(r.received, PREFERENCE_DAYS)})

    if days_since_purchase <= DEFECT_EXCHANGE_DAYS:
        return _decision("allowed", "§4.2", "Manufacturing defects are exchanged by the store. Damage from misuse, falls, "
                         "excess humidity or unauthorized changes is not covered.",
                         {**facts, **deadline(r.order_date, DEFECT_EXCHANGE_DAYS)})
    if days_since_received <= LEGAL_WARRANTY_DAYS:
        # §4.2 sends the customer to the manufacturer after 30 days, but §8.1 still grants the 90-day legal warranty.
        return _decision("needs_human", "§8.1", "Past the 30-day store exchange but inside the 90-day legal warranty: "
                         "the team handles it.", {**facts, **deadline(r.received, LEGAL_WARRANTY_DAYS)})
    return _decision("manufacturer_warranty", "§4.2", "Past the legal warranty. The manufacturer warranty certificate "
                     "applies (6 months to 2 years) and the store can mediate on request.", facts)


def _decision(decision: str, section: str, explanation: str, facts: dict | None = None) -> dict:
    return {"decision": decision, "policy_section": section, "explanation": explanation,
            "must_confirm_with_customer": "Not customized, not a 'final sale' item, not a wind instrument mouthpiece (§4.4).",
            **(facts or {})}
