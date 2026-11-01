"""The tools the model can call.

They are typed and read-only, with no free SQL: an agent that writes queries could read any customer's order, and an
instruction in the prompt would be the only thing stopping it. Here identity is checked in code, before any data exists
in the conversation, so no prompt injection can reach another customer's order.
"""
import hashlib
import json
import re
from datetime import date
from functools import lru_cache

from . import config, db, rules
from .policies import PolicyIndex
from .store import Store

MAX_FAILED_CHECKS = 3
RETURN_REASONS = ("regret", "defect", "preference")
HANDOFF_REASONS = ("complaint", "late_delivery", "order_change", "return_needs_person", "policy_doubt", "customer_asked")


def _function(name: str, description: str, properties: dict, required: tuple = ()) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": list(required)}}}


SCHEMAS = [
    _function("search_products",
              "Busca no catálogo atual: preço, estoque, promoção vigente e especificações. Use para qualquer pergunta "
              "sobre produto, mesmo que você ache que sabe a resposta. Com nome de produto, mostra também os indisponíveis.",
              {"query": {"type": "string", "description": "Nome, marca, modelo ou característica. Vazio para navegar por categoria."},
               "category": {"type": "string", "description": "Guitarras, Baixos, Baterias e Percussão, Teclados e Pianos, Violões, Instrumentos de Sopro, Cordas Orquestrais ou Ukuleles."},
               "min_price": {"type": "number"},
               "max_price": {"type": "number"},
               "on_promotion": {"type": "boolean", "description": "true para listar só o que está em promoção hoje."}}),
    _function("get_order",
              "Consulta um pedido. Exige o número do pedido e o telefone ou e-mail usado na compra; peça o que faltar. "
              "Depois de verificado, o mesmo pedido não precisa de contato de novo nesta conversa.",
              {"order_id": {"type": "integer"},
               "contact": {"type": "string", "description": "Telefone ou e-mail informado pelo cliente nesta conversa."}},
              ("order_id",)),
    _function("check_return",
              "Aplica as regras de devolução e troca a um pedido e devolve a decisão, o prazo e a seção do manual. "
              "Use sempre que o cliente quiser devolver ou trocar um pedido; nunca decida prazo por conta própria.",
              {"order_id": {"type": "integer"},
               "contact": {"type": "string"},
               "reason": {"type": "string", "enum": list(RETURN_REASONS),
                          "description": "regret = arrependimento · defect = defeito · preference = cor, modelo ou tamanho."},
               "received_date": {"type": "string", "description": "Data em que o cliente recebeu, AAAA-MM-DD, se ele informou."}},
              ("order_id", "reason")),
    _function("simulate_payment",
              "Calcula preço no PIX e parcelas sem juros para um valor. Use para qualquer conta de pagamento.",
              {"amount": {"type": "number"},
               "on_promotion": {"type": "boolean", "description": "true se o valor já é preço promocional."}},
              ("amount",)),
    _function("search_policies",
              "Busca no manual da loja: endereço, contatos, horários, pagamento, trocas, frete, promoções, garantia, "
              "privacidade e o que a loja vende.",
              {"query": {"type": "string"}}, ("query",)),
    _function("escalate_to_human",
              "Encaminha para a equipe e devolve o protocolo. Use em reclamação, entrega atrasada, cancelamento ou "
              "alteração de pedido, caso que as ferramentas mandem para a equipe, ou quando o cliente pedir uma pessoa.",
              {"reason": {"type": "string", "enum": list(HANDOFF_REASONS)},
               "summary": {"type": "string", "description": "Resumo curto para a equipe, sem dados pessoais."}},
              ("reason", "summary")),
]


@lru_cache
def store() -> Store:
    return Store.load()


@lru_cache
def policies() -> PolicyIndex:
    return PolicyIndex.load()


def _authorize(order_id: int, contact: str, ctx: dict) -> dict | None:
    """Returns None when access is allowed. Unknown order and wrong contact give the same answer on purpose."""
    if order_id in ctx.setdefault("verified_orders", []):
        return None
    if ctx.get("failed_checks", 0) >= MAX_FAILED_CHECKS:
        return {"status": "locked", "instruction": "Limite de tentativas atingido. Encaminhe para a equipe."}
    if not contact:
        return {"status": "needs_contact", "instruction": "Peça o telefone ou e-mail usado na compra."}
    if store().contact_matches(order_id, contact):
        ctx["verified_orders"].append(order_id)
        return None
    ctx["failed_checks"] = ctx.get("failed_checks", 0) + 1
    return {"status": "not_verified", "instruction": "Não foi possível confirmar pedido e contato. Não revele se o pedido existe."}


def search_products(ctx: dict, query: str = "", category: str = "", min_price: float | None = None,
                    max_price: float | None = None, on_promotion: bool = False) -> dict:
    return store().search(query, category, min_price, max_price, on_promotion)


def get_order(ctx: dict, order_id: int, contact: str = "") -> dict:
    denied = _authorize(order_id, contact, ctx)
    return denied or {"status": "ok", "order": store().order_details(order_id)}


def check_return(ctx: dict, order_id: int, reason: str, contact: str = "", received_date: str = "") -> dict:
    denied = _authorize(order_id, contact, ctx)
    if denied:
        return denied
    received = date.fromisoformat(received_date) if received_date else None
    details = store().order_details(order_id)
    return {"status": "ok", "customer_first_name": details["customer_first_name"], "items": details["items"],
            "today": config.DATA_AS_OF.isoformat(), **store().return_decision(order_id, reason, received)}


def simulate_payment(ctx: dict, amount: float, on_promotion: bool = False) -> dict:
    return rules.payment_options(amount, on_promotion)


def search_policies(ctx: dict, query: str) -> dict:
    return {"sections": [{"section": s.number, "title": s.title, "text": s.text} for s in policies().search(query)]}


def escalate_to_human(ctx: dict, reason: str, summary: str) -> dict:
    protocol = "EM-" + hashlib.sha1(f"{ctx.get('thread_id')}{summary}".encode()).hexdigest()[:6].upper()
    db.save_handoff(protocol, ctx.get("thread_id", ""), reason, summary, config.now().isoformat())
    return {"protocol": protocol, "response_time": "até 24 horas úteis"}


HANDLERS = {f.__name__: f for f in (search_products, get_order, check_return, simulate_payment, search_policies,
                                    escalate_to_human)}


def _coerce_order_id(arguments: dict) -> dict:
    """Models send "#12" as often as 12."""
    if "order_id" in arguments:
        arguments["order_id"] = int(re.sub(r"\D", "", str(arguments["order_id"])) or 0)
    return arguments


def execute(name: str, raw_arguments: str, ctx: dict) -> dict:
    """Bad tool calls go back to the model as an error it can fix, not as a crash in the customer's face."""
    if name not in HANDLERS:
        return {"error": f"unknown tool {name}"}
    try:
        return HANDLERS[name](ctx, **_coerce_order_id(json.loads(raw_arguments or "{}")))
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        return {"error": f"invalid arguments: {error}"}
