import pytest

from emporio.store import AVAILABLE, COMING_SOON, DISCONTINUED, OUT_OF_STOCK, Store


@pytest.fixture(scope="module")
def store():
    return Store.load()


def names(result):
    return [p["name"] for p in result["products"]]


def test_loads_every_csv_row(store):
    assert (len(store.products), len(store.orders), len(store.customers)) == (65, 20, 50)


def test_only_active_promotions_are_kept(store):
    assert sorted(store.promotions) == [90, 94, 121, 127]


@pytest.mark.parametrize("typed", ["Takamine GD20", "takamine gd-20", "GD 20", "gd20"])
def test_model_name_matches_however_it_is_typed(store, typed):
    assert names(store.search(typed)) == ["Takamine GD20 Dreadnought Natural"]


def test_expired_promotion_does_not_change_the_price(store):
    gd20 = store.search("GD20")["products"][0]
    assert gd20["price_brl"] == 2199 and "promotion" not in gd20


def test_active_promotion_shows_original_price_and_blocks_pix_discount(store):
    crafter = store.search("Crafter HT-100")["products"][0]
    assert crafter["price_brl"] == 1967.18
    assert crafter["promotion"]["original_price_brl"] == 2399 and crafter["promotion"]["discount_percent"] == 18
    assert crafter["pix_price_brl"] is None


def test_browsing_hides_what_cannot_be_bought(store):
    result = store.search(category="Violões", max_price=1000, limit=50)
    found = names(result)
    assert "Giannini GF-3D Dreadnought Sunburst" not in found  # out of stock
    assert "Shelby SN-7C 7 Cordas Nylon Natural" not in found  # discontinued
    assert "Tagima TW-7 7 Cordas Aço Natural" in found         # R$ 999, inside the budget
    assert result["total_found"] == 12  # counted by hand from products.csv
    assert all(p["availability"] == AVAILABLE for p in result["products"])


@pytest.mark.parametrize("query, status", [("GF-3D", OUT_OF_STOCK), ("SN-7C", DISCONTINUED), ("KA-ABP-CTG", COMING_SOON)])
def test_naming_an_unavailable_product_explains_it_and_offers_alternatives(store, query, status):
    result = store.search(query)
    assert result["products"][0]["availability"] == status
    assert 1 <= len(result["alternatives"]) <= 3
    assert all(a["availability"] == AVAILABLE for a in result["alternatives"])


def test_coming_soon_has_no_price_even_with_stock_in_the_csv(store):
    card = store.search("KA-ABP-CTG")["products"][0]
    assert "price_brl" not in card and "ainda não está à venda" in card["availability_note"]


def test_empty_search_says_it_is_not_in_the_catalog(store):
    result = store.search("flauta transversal")
    assert "não tem isso no catálogo" in result["note"]
    assert "Instrumentos de Sopro (Madeiras)" not in result["categories_in_stock"]


def test_promotion_filter_lists_only_live_promotions(store):
    assert store.search(on_promotion=True)["total_found"] == 4


def test_typo_still_finds_the_product(store):
    assert "Yamaha C40 Nylon Natural" in names(store.search("yamha c40"))


def test_accessories_are_not_in_the_catalog(store):
    assert store.search("palheta")["total_found"] == 0


def test_price_filter_uses_the_promotional_price(store):
    assert "Ohana CK-20 Concert Natural" in names(store.search(category="Ukuleles", max_price=440, limit=50))


@pytest.mark.parametrize("contact, ok", [
    ("(67) 98432-1098", True), ("67984321098", True), ("98432-1098", True),
    ("PEDRO.OLIVEIRA@JMAIL.COM", True),
    ("(67) 99999-9999", False), ("1098", False), ("outro@jmail.com", False), ("", False),
])
def test_order_requires_the_contact_on_the_order(store, contact, ok):
    assert store.contact_matches(1, contact) is ok


def test_unknown_order_fails_like_a_wrong_contact(store):
    assert store.contact_matches(999, "(67) 98432-1098") is False


def test_order_details_never_expose_contact_data(store):
    text = str(store.order_details(1))
    assert "pedro.oliveira" not in text and "98432" not in text and "Oliveira" not in text


def test_shipped_order_past_its_estimate_is_late(store):
    assert store.order_details(8)["is_late"] is True


def test_pending_order_has_no_tracking_fields(store):
    details = store.order_details(13)
    assert "tracking_code" not in details and "estimated_delivery" not in details


def test_order_with_a_tracking_code_counts_as_remote_purchase(store):
    assert store.return_decision(1, "regret", None)["decision"] == "denied"
    assert store.return_decision(1, "regret", None)["policy_section"] == "§4.1"
