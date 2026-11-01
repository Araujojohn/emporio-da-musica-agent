"""Retrieval is measured apart from the model: free, deterministic, and the failure is easy to locate."""
import pytest

from emporio.policies import HEADINGS, PolicyIndex

GOLDEN = [
    ("qual o endereço da loja?", "1.2"),
    ("onde vocês ficam?", "1.2"),
    ("qual o telefone de vocês?", "1.2"),
    ("qual o cnpj?", "1.2"),
    ("que horas vocês abrem no sábado?", "2"),
    ("funciona domingo?", "2"),
    ("abre em feriado?", "2"),
    ("aceita pix?", "3"),
    ("tem desconto no pix?", "3"),
    ("posso pagar no boleto?", "3"),
    ("em quantas vezes posso parcelar?", "3.1"),
    ("qual a parcela mínima?", "3.1"),
    ("posso pagar metade no pix e metade no cartão?", "3.1"),
    ("me arrependi da compra, posso devolver?", "4.1"),
    ("quero desistir da compra online", "4.1"),
    ("em quanto tempo sai o reembolso?", "4.1"),
    ("o instrumento veio com defeito, e agora?", "4.2"),
    ("o violão chegou quebrado", "4.2"),
    ("quero trocar por outra cor", "4.3"),
    ("posso trocar produto de liquidação com venda final?", "4.4"),
    ("posso trocar boquilha de saxofone?", "4.4"),
    ("qual o valor do frete em campo grande?", "5.1"),
    ("tem frete grátis?", "5.1"),
    ("vocês enviam para outra cidade pelos correios?", "5.2"),
    ("quanto demora o sedex?", "5.2"),
    ("como rastreio meu pedido?", "5.3"),
    ("vai ter black friday?", "6.1"),
    ("promoção acumula com desconto do pix?", "6.2"),
    ("qual a garantia dos produtos?", "8.1"),
    ("a garantia cobre cordas gastas?", "8.3"),
    ("como apago meus dados?", "9"),
    ("vocês vendem cordas e palhetas?", "1"),
]


@pytest.fixture(scope="module")
def index():
    return PolicyIndex.load()


def test_every_heading_was_found_in_the_pdf(index):
    assert len(index.sections) == len(HEADINGS)
    assert all(s.text for s in index.sections if s.number not in ("5", "6", "8"))  # those are only parent headings


def test_pdf_page_furniture_is_removed(index):
    assert not any("Página 4" in s.text or "Manual de Políticas" in s.text for s in index.sections)


def test_section_keeps_its_rule_together(index):
    regret = next(s for s in index.sections if s.number == "4.1")
    assert "7 (sete) dias corridos" in regret.text and "10 dias úteis" in regret.text


def test_contradictions_are_annotated(index):
    whatsapp = next(s for s in index.sections if s.number == "7")
    assert "3321-4500" in whatsapp.text and "(67) 3341-4444" in whatsapp.text


@pytest.mark.parametrize("question, section", GOLDEN)
def test_expected_section_is_in_the_top_three(index, question, section):
    assert section in [s.number for s in index.search(question)]


def test_retrieval_quality_does_not_regress(index):
    ranks = []
    for question, section in GOLDEN:
        found = [s.number for s in index.search(question)]
        ranks.append(found.index(section) + 1 if section in found else 0)
    recall_at_3 = sum(r > 0 for r in ranks) / len(ranks)
    mrr = sum(1 / r for r in ranks if r) / len(ranks)
    assert recall_at_3 == 1.0
    assert mrr >= 0.8
