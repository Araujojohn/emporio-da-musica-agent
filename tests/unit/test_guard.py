import pytest

from emporio import guard

EVIDENCE = '{"price_brl": 2199.0, "pix_price_brl": 2089.05, "estimated_delivery": "2025-11-15", "stock": 5} contato@emporiodamusica.com.br'


@pytest.mark.parametrize("reply", [
    "Custa R$ 2.199,00 e no PIX R$ 2.089,05.",
    "Sai por R$ 2199 ou cerca de R$ 2.089.",
    "Chegou em 15/11/2025.",
    "São 5 unidades, em até 12x, 3 opções.",
    "It costs R$ 2,199.00, or R$ 2,089.05 with PIX.",
    "Escreve pra contato@emporiodamusica.com.br.",
])
def test_supported_replies_pass(reply):
    assert guard.unverified(reply, EVIDENCE) == []


@pytest.mark.parametrize("reply, problem", [
    ("Custa R$ 1.935,12.", "1.935,12"),                    # the expired promotion price
    ("Ligue para (67) 3321-4500.", "3321"),
    ("Escreva para vendas@emporio.com.", "vendas@emporio.com"),
    ("Puxa, [nome], que pena.", "[nome]"),
])
def test_unsupported_data_is_caught(reply, problem):
    assert problem in guard.unverified(reply, EVIDENCE)


@pytest.mark.parametrize("reply", ["O Yamaha C40 é ótimo.", "Temos o Kala KA-15S e o GF-3D.", "O Takamine GD20 chegou."])
def test_product_model_names_are_not_quantities(reply):
    assert guard.unverified(reply, "") == []


@pytest.mark.parametrize("reply", ["Em 24x sem juros.", "Ligue 3321-4500.", "R$ 40,00 por mês."])
def test_real_figures_still_need_a_source(reply):
    assert guard.unverified(reply, "") != []


def test_number_from_the_customers_own_message_is_allowed():
    assert guard.unverified("Pedido 4821 anotado.", "cadê meu pedido 4821?") == []


def test_cut_removes_only_the_sentence_with_the_bad_number():
    reply = "O violão é ótimo. Custa R$ 999,00! Quer saber mais?"
    assert guard.cut_sentences(reply, ["999,00"]) == "O violão é ótimo. Quer saber mais?"
