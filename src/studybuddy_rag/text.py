"""Text utilities: tokenisation and a sentence splitter that respects decimals and abbreviations."""
from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")

STOPWORDS = frozenset(
    """a an and are as at be by can do does for from has have how i in is it its me my of on or
    so that the their them then there these this to was what when where which who why will with
    you your about into than also not no yes please tell explain""".split()
)

# Abbreviations whose trailing period does not end a sentence.
_ABBREVIATIONS = frozenset(
    "e.g i.e etc vs mr mrs ms dr prof fig figs eq eqs no approx ca cf st jr sr al".split()
)

_SENTENCE_END_RE = re.compile(r"([.!?])(\s+)")


def tokenize(text: str, *, drop_stopwords: bool = False) -> list[str]:
    tokens = _TOKEN_RE.findall(text.lower())
    if drop_stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS]
    return tokens


def stem(token: str) -> str:
    """A light suffix fold so "fractions" ~ "fraction" and "dividing" ~ "divid"."""
    for suffix in ("ing", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def terms(text: str) -> list[str]:
    """Stemmed content words: the shared vocabulary of BM25 and the hashing embedder."""
    return [stem(t) for t in tokenize(text, drop_stopwords=True)]


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences without breaking ``3.14``, ``e.g.`` or ``Dr. Smith``.

    A boundary is a ``.``/``!``/``?`` followed by whitespace, where the word before a ``.`` is not
    a known abbreviation or a single initial. Decimals never match because a boundary needs
    whitespace after the period.
    """
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END_RE.finditer(text):
        end = match.end(1)
        if match.group(1) == ".":
            prev_word = text[start:match.start(1)].rsplit(" ", 1)[-1].lower().rstrip(".")
            if prev_word in _ABBREVIATIONS or (len(prev_word) == 1 and prev_word.isalpha()):
                continue
        piece = text[start:end].strip()
        if piece:
            sentences.append(piece)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences
