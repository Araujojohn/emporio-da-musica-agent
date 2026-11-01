"""Checks every reply before the customer sees it.

Every number and e-mail in the reply must come from this turn's tool results, the customer's own message or the clock.
The guard needs no list of forbidden prices: a figure the model invented simply has no source. It covers the expensive
mistakes in this domain: wrong price, wrong deadline and phone numbers or e-mails from somewhere else.
"""
import re

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
_PLACEHOLDER = re.compile(r"\[[^\]\d]{2,20}\]|\{[^}]{2,20}\}")  # "[nome]", seen in the first live test
SMALL_NUMBER = 12  # "3 opções", "12x": too common to verify and harmless alone


def _value(text: str) -> float:
    """Reads Brazilian format: "1.967,18" → 1967.18 · "1.200" → 1200 · "599.9" → 599.9."""
    if "," in text:
        return float(text.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
        return float(text.replace(".", ""))
    return float(text) if text.count(".") <= 1 else float(text.replace(".", ""))


def _sources(text: str) -> set[float]:
    return {_value(token) for token in _NUMBER.findall(text)}


def _is_supported(number: float, sources: set[float]) -> bool:
    if number <= SMALL_NUMBER and number == int(number):
        return True
    return any(abs(number - source) < 0.01 or number in (round(source), int(source)) for source in sources)


def unverified(reply: str, evidence: str) -> list[str]:
    """Numbers, e-mails and unfilled placeholders in the reply that nothing in the evidence supports."""
    sources = _sources(evidence)
    clean = _EMAIL.sub(" ", reply)
    numbers = [t for t in _NUMBER.findall(clean) if not _is_supported(_value(t), sources)]
    emails = [e for e in _EMAIL.findall(reply) if e.lower() not in evidence.lower()]
    return numbers + emails + _PLACEHOLDER.findall(reply)


def cut_sentences(reply: str, unsupported: list[str]) -> str:
    """Removes only what cannot be verified, so the rest of a good answer survives."""
    parts = re.split(f"({_SENTENCE_END.pattern})", reply)
    kept = [part for part in parts if not any(token in part for token in unsupported)]
    return re.sub(r"[ \t]{2,}", " ", "".join(kept)).strip()
