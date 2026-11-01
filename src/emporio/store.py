"""The store's operational data: loads the CSVs and answers catalog and order questions.

The CSVs are read into plain dicts once. There are 65 products and 20 orders, so a database would add a moving part
without adding anything. Findings about the data are documented in docs/data-audit.md.
"""
import csv
import difflib
import json
import re
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from pathlib import Path

from . import rules
from .config import DATA_AS_OF, DATA_DIR
from .text import compact, normalize, words

ORDER_STATUS = {"pending": "aguardando confirmação", "confirmed": "confirmado, em preparação", "shipped": "enviado",
                "delivered": "entregue", "cancelled": "cancelado"}
PAYMENT = {"pix": "PIX", "debit": "débito", "boleto": "boleto", "credit_3x": "crédito em 3x",
           "credit_6x": "crédito em 6x", "credit_12x": "crédito em 12x"}
AVAILABLE, OUT_OF_STOCK, DISCONTINUED, COMING_SOON = "available", "out_of_stock", "discontinued", "coming_soon"
STOPWORDS = {"o", "a", "os", "as", "de", "do", "da", "dos", "das", "um", "uma", "para", "pra", "com", "e", "em"}
MIN_CONTACT_DIGITS = 8
# Said in words because the model read "coming_soon" plus alternatives as "esgotado" in the first eval run.
AVAILABILITY_NOTES = {
    OUT_OF_STOCK: "Temporariamente sem estoque.",
    DISCONTINUED: "Descontinuado: não faz mais parte do catálogo.",
    COMING_SOON: "Lançamento: chega em breve e ainda não está à venda. Sem preço definido.",
}
NOT_IN_CATALOG = "Nada encontrado: a loja não tem isso no catálogo hoje. Não diga que está esgotado."


def _read(name: str, folder: Path) -> list[dict]:
    with open(folder / f"{name}.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


@dataclass
class Store:
    products: dict[int, dict]
    categories: dict[int, str]
    promotions: dict[int, dict]  # active promotions only, by product id
    orders: dict[int, dict]
    items: dict[int, list[dict]]
    customers: dict[int, dict]

    @classmethod
    def load(cls, folder: Path = DATA_DIR) -> "Store":
        products = {int(p["product_id"]): {
            **p,
            "product_id": int(p["product_id"]),
            "category_id": int(p["category_id"]),
            "price_brl": float(p["price_brl"]),
            "stock_quantity": int(p["stock_quantity"]),
            "specs": json.loads(p["specs"]),
        } for p in _read("products", folder)}
        promotions = {}
        for row in _read("promotions", folder):
            # 21 of the 25 rows are expired. A product can have several expired rows and at most one active.
            if row["is_active"] == "1":
                promotions[int(row["product_id"])] = {"discount_percent": float(row["discount_percent"]),
                                                      "name": row["description"]}
        items: dict[int, list[dict]] = {}
        for row in _read("order_items", folder):
            items.setdefault(int(row["order_id"]), []).append(
                {"product_id": int(row["product_id"]), "quantity": int(row["quantity"])})
        return cls(
            products=products,
            categories={int(c["category_id"]): c["name"] for c in _read("categories", folder)},
            promotions=promotions,
            orders={int(o["order_id"]): o for o in _read("orders", folder)},
            items=items,
            customers={int(c["customer_id"]): c for c in _read("customers", folder)},
        )

    def availability(self, product: dict) -> str:
        if product["status"] == "discontinued":
            return DISCONTINUED
        if product["status"] == "coming_soon":  # the CSV shows stock for these, but they are not on sale yet
            return COMING_SOON
        return AVAILABLE if product["stock_quantity"] > 0 else OUT_OF_STOCK

    def price_now(self, product: dict) -> float:
        promotion = self.promotions.get(product["product_id"])
        return rules.promo_price(product["price_brl"], promotion["discount_percent"]) if promotion else product["price_brl"]

    def card(self, product: dict) -> dict:
        """What the agent sees about a product. Prices are final: the model never computes a discount."""
        availability = self.availability(product)
        promotion = self.promotions.get(product["product_id"])
        price = self.price_now(product)
        card = {
            "product_id": product["product_id"],
            "name": product["name"],
            "category": self.categories[product["category_id"]],
            "availability": availability,
            "description": product["description"],
            "specs": product["specs"],
        }
        if availability in AVAILABILITY_NOTES:
            card["availability_note"] = AVAILABILITY_NOTES[availability]
        if availability in (AVAILABLE, OUT_OF_STOCK):
            card["price_brl"] = price
        if availability == AVAILABLE:
            card["stock"] = product["stock_quantity"]
            card["pix_price_brl"] = rules.pix_price(price, bool(promotion))
            card["max_interest_free_installments"] = rules.max_installments(price)
            if promotion:
                card["promotion"] = {"name": promotion["name"], "discount_percent": promotion["discount_percent"],
                                     "original_price_brl": product["price_brl"]}
        return card

    @cached_property
    def _search_index(self) -> dict[int, tuple[set[str], str]]:
        index = {}
        for pid, p in self.products.items():
            text = " ".join([p["name"], self.categories[p["category_id"]], p["description"],
                             " ".join(str(v) for v in p["specs"].values())])
            index[pid] = (set(words(text)), compact(p["name"]))
        return index

    def _vocabulary(self) -> list[str]:
        return sorted({w for tokens, _ in self._search_index.values() for w in tokens})

    def _matches(self, query: str) -> list[int]:
        terms = [w for w in words(query) if w not in STOPWORDS]
        if not terms:
            return list(self.products)
        fused = compact(query)
        exact = [pid for pid, (_, name) in self._search_index.items() if fused in name]
        if exact:
            return exact
        vocabulary = self._vocabulary()
        expanded = [{t, t.rstrip("s"), *difflib.get_close_matches(t, vocabulary, n=3, cutoff=0.8)} for t in terms]
        hits = {pid: sum(bool(options & tokens) for options in expanded)
                for pid, (tokens, _) in self._search_index.items()}
        best = max(hits.values())
        return [pid for pid, score in hits.items() if score == best] if best else []

    def search(self, query: str = "", category: str = "", min_price: float | None = None,
               max_price: float | None = None, on_promotion: bool = False, limit: int = 12) -> dict:
        """Naming a product shows it whatever its status. Browsing shows only what can be bought today."""
        found = [self.products[pid] for pid in self._matches(query)]
        if on_promotion:
            found = [p for p in found if p["product_id"] in self.promotions]
        if category:
            wanted = normalize(category).rstrip("s")
            found = [p for p in found if wanted in normalize(self.categories[p["category_id"]])]
        if not query:
            found = [p for p in found if self.availability(p) == AVAILABLE]
        if max_price is not None:
            found = [p for p in found if self.price_now(p) <= max_price]
        if min_price is not None:
            found = [p for p in found if self.price_now(p) >= min_price]
        found.sort(key=lambda p: (self.availability(p) != AVAILABLE, self.price_now(p)))
        cards = [self.card(p) for p in found[:limit]]
        result = {"total_found": len(found), "shown": len(cards), "products": cards}
        if not found:
            result["note"] = NOT_IN_CATALOG
            # Without this the model offered "sax or clarinet", which the store lists as a category but does not stock
            result["categories_in_stock"] = sorted({self.categories[p["category_id"]] for p in self.products.values()
                                                    if self.availability(p) == AVAILABLE})
        elif all(self.availability(p) != AVAILABLE for p in found):
            result["alternatives"] = self._alternatives(found[0])
        return result

    def _alternatives(self, product: dict) -> list[dict]:
        """§7.3: an unavailable product comes with similar ones the customer can actually buy."""
        same_category = [p for p in self.products.values()
                         if p["category_id"] == product["category_id"] and self.availability(p) == AVAILABLE]
        same_category.sort(key=lambda p: abs(self.price_now(p) - product["price_brl"]))
        return [self.card(p) for p in same_category[:3]]

    def contact_matches(self, order_id: int, contact: str) -> bool:
        """The customer proves identity with the phone or e-mail on the order."""
        order = self.orders.get(order_id)
        if not order:
            return False
        customer = self.customers.get(int(order["customer_id"]), {})
        if "@" in contact:
            return contact.strip().lower() == customer.get("email", "").lower()
        digits = _digits(contact)
        return len(digits) >= MIN_CONTACT_DIGITS and _digits(customer.get("phone", "")).endswith(digits)

    def order_details(self, order_id: int) -> dict:
        """Call only after contact_matches. Phone, e-mail and full name never reach the model."""
        order = self.orders[order_id]
        estimate = order["estimated_delivery"]
        details = {
            "order_id": order_id,
            "customer_first_name": self.customers[int(order["customer_id"])]["name"].split()[0],
            "status": ORDER_STATUS[order["status"]],
            "order_date": order["order_date"],
            "total_brl": float(order["total_brl"]),
            "payment": PAYMENT[order["payment_method"]],
            "items": [{"name": self.products[i["product_id"]]["name"], "quantity": i["quantity"]}
                      for i in self.items.get(order_id, [])],
        }
        if order["tracking_code"]:
            details["tracking_code"] = order["tracking_code"]
        if estimate:
            details["estimated_delivery"] = estimate
            details["is_late"] = order["status"] == "shipped" and date.fromisoformat(estimate) < DATA_AS_OF
        if order["notes"]:
            details["notes"] = order["notes"]
        return details

    def return_decision(self, order_id: int, reason: str, received: date | None, today: date = DATA_AS_OF) -> dict:
        order = self.orders[order_id]
        estimate = order["estimated_delivery"]
        order_date = date.fromisoformat(order["order_date"])
        return rules.return_decision(rules.ReturnRequest(
            reason=reason,
            status=order["status"],
            order_date=order_date,
            received=received or (date.fromisoformat(estimate) if estimate else None),
            received_is_estimate=received is None,
            bought_remotely=bool(order["tracking_code"]),
            today=today,
        ))
