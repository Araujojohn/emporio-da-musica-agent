"""Text helpers shared by catalog search and policy retrieval."""
import re
import unicodedata


def normalize(text: str) -> str:
    """Lowercase, no accents: customers type "violao" and "violão" interchangeably."""
    without_accents = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return without_accents.lower()


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize(text))


def compact(text: str) -> str:
    """"GD-20" and "gd 20" both become "gd20", so model names match however they are typed."""
    return "".join(words(text))


def stem(word: str) -> str:
    """Light Portuguese stemmer: enough to join "devolução/devoluções/devolver" style variations."""
    for suffix, replacement in (("coes", "cao"), ("oes", "ao"), ("ais", "al"), ("eis", "el"), ("ns", "m")):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[: -len(suffix)] + replacement
    if word.endswith("s") and len(word) > 3:
        return word[:-1]
    return word
