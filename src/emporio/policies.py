"""Retrieval over the store manual.

The manual is 8 pages with clear headings, so each numbered section is one chunk: a section is the unit a customer's
question maps to, and sliding windows would only split rules from their conditions. Ranking is BM25. The test suite
measures it (tests/unit/test_retrieval.py); embeddings would add a provider and a vector store for a corpus of 30 chunks.
"""
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from pypdf import PdfReader
from rank_bm25 import BM25Okapi

from .config import DATA_DIR
from .text import normalize, stem, words

HEADINGS = [
    "1. Sobre a Empório da Música", "1.1 Missão", "1.2 Dados da Empresa", "2. Horário de Funcionamento",
    "3. Formas de Pagamento", "3.1 Regras de Parcelamento", "4. Política de Trocas e Devoluções",
    "4.1 Direito de Arrependimento (Compras Online)", "4.2 Trocas por Defeito", "4.3 Trocas por Preferência",
    "4.4 Itens Não Elegíveis para Troca", "5. Política de Frete e Entregas",
    "5.1 Entregas na Região Metropolitana de Campo Grande", "5.2 Entregas para Outras Cidades",
    "5.3 Código de Rastreamento", "6. Promoções e Descontos", "6.1 Tipos de Promoção", "6.2 Regras de Promoções",
    "7. Atendimento via WhatsApp", "7.1 Diretrizes de Atendimento", "7.2 Fluxo de Atendimento Padrão",
    "7.3 Situações Especiais", "8. Garantia", "8.1 Garantia Legal", "8.2 Garantia do Fabricante",
    "8.3 O que Não Cobre a Garantia", "9. Privacidade e Proteção de Dados", "10. Disposições Finais",
]
# Contradictions in the manual, resolved once here and documented in docs/data-audit.md.
ERRATA = {
    "1.2": "Nota: o e-mail correto é contato@emporiodamusica.com.br.",
    "3": "Nota: as parcelas mínimas válidas são as da seção 3.1.",
    "4.2": "Nota: depois de 30 dias ainda vale a garantia legal de 90 dias da seção 8.1, tratada pela equipe.",
    "7": "Nota: o WhatsApp oficial é o (67) 3341-4444, o mesmo da seção 1.2.",
}
# How customers say it → how the manual says it.
SYNONYMS = {
    "devolver": "devolucao arrependimento", "arrependi": "arrependimento devolucao", "desistir": "arrependimento",
    "reembolso": "arrependimento devolucao", "estorno": "arrependimento",
    "trocar": "troca preferencia", "quebrado": "defeito", "quebrou": "defeito", "estragado": "defeito",
    "aberto": "horario funcionamento", "abre": "horario funcionamento", "fecha": "horario funcionamento",
    "funciona": "horario funcionamento", "hora": "horario", "domingo": "horario funcionamento", "sabado": "horario",
    "feriado": "horario", "onde": "endereco", "localizacao": "endereco", "fica": "endereco", "endereco": "dados empresa",
    "telefone": "dados empresa whatsapp", "contato": "dados empresa", "cnpj": "dados empresa",
    "parcelar": "parcelamento", "parcela": "parcelamento", "parcelado": "parcelamento", "vezes": "parcelamento",
    "cartao": "pagamento credito", "pagar": "pagamento", "pix": "pagamento desconto", "boleto": "pagamento",
    "frete": "entrega", "envio": "entrega", "enviar": "entrega", "correios": "entrega", "demora": "prazo entrega",
    "chega": "prazo entrega", "rastrear": "rastreamento", "rastreio": "rastreamento",
    "cupom": "desconto promocao", "liquidacao": "promocao", "acumular": "cumulatividade", "juntar": "cumulatividade",
    "conserto": "garantia", "reclamar": "reclamacao", "acessorio": "escopo acessorios", "corda": "acessorios",
    "dado": "privacidade", "lgpd": "privacidade", "excluir": "exclusao dados",
}


@dataclass(frozen=True)
class Section:
    number: str
    title: str
    text: str


def extract_sections(pdf: Path) -> list[Section]:
    raw = " ".join(page.extract_text() for page in PdfReader(pdf).pages)
    clean = re.sub(r"\s+", " ", raw)
    clean = re.sub(r"Empório da Música Manual de Políticas e Procedimentos", " ", clean)
    clean = re.sub(r"Página \d+", " ", clean)
    clean = re.sub(r"\s+", " ", clean)
    cursor = 0
    spans = []
    for heading in HEADINGS:
        start = clean.index(heading, cursor)
        spans.append((heading, start))
        cursor = start + len(heading)
    sections = []
    for (heading, start), next_span in zip(spans, spans[1:] + [("", len(clean))]):
        number, title = heading.split(" ", 1)
        number = number.rstrip(".")
        body = clean[start + len(heading):next_span[1]].strip()
        if number in ERRATA:
            body = f"{body} {ERRATA[number]}"
        sections.append(Section(number, title, body))
    return sections


def _tokens(text: str) -> list[str]:
    return [stem(w) for w in words(text) if len(w) > 1]


def _expand(query: str) -> str:
    extra = [SYNONYMS[w] for w in words(query) if w in SYNONYMS]
    return " ".join([normalize(query), *extra])


class PolicyIndex:
    def __init__(self, sections: list[Section]):
        self.sections = sections

    @classmethod
    def load(cls) -> "PolicyIndex":
        return cls(extract_sections(DATA_DIR / "store_policies.pdf"))

    @cached_property
    def _bm25(self) -> BM25Okapi:
        # The title counts three times: a section about "Garantia" should beat one that mentions it in passing
        return BM25Okapi([_tokens(f"{s.title} {s.title} {s.title} {s.text}") for s in self.sections])

    def search(self, query: str, k: int = 3) -> list[Section]:
        scores = self._bm25.get_scores(_tokens(_expand(query)))
        ranked = sorted(range(len(self.sections)), key=lambda i: scores[i], reverse=True)
        return [self.sections[i] for i in ranked[:k] if scores[i] > 0]
