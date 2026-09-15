from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache

from spellchecker import SpellChecker

from text_verification.compatibility.text_context import TextContext

_WORDS = re.compile(r"(?<![A-Za-z0-9_'])[A-Za-z]{3,32}(?![A-Za-z0-9_'])")
_BASE_VERBS = {
    "go": "goes", "have": "has", "do": "does", "work": "works",
    "walk": "walks", "run": "runs", "eat": "eats", "play": "plays",
    "like": "likes", "need": "needs", "want": "wants", "know": "knows",
    "say": "says", "make": "makes", "take": "takes", "use": "uses",
}
_SINGULAR = {**_BASE_VERBS, "are": "is", "don't": "doesn't"}
_PLURAL = {
    **{value: key for key, value in _BASE_VERBS.items()},
    "is": "are", "was": "were", "doesn't": "don't",
}
_SUBJECT_VERB = re.compile(
    r"(?:^|(?<=[.!?。！？\n]))[ \t]*(?:[\"“][ \t]*)?"
    r"(he|she|it|they|we|you|I)[ \t]+"
    r"(?:(?:always|usually|often|sometimes|never|really|already|still|also)[ \t]+)?"
    r"(" + "|".join(sorted(_SINGULAR.keys() | _PLURAL.keys(), key=len, reverse=True)) + r")"
    r"(?![A-Za-z0-9_'])",
    re.IGNORECASE,
)
_DIALECT_WORDS = frozenset({
    "colour", "colours", "coloured", "colouring", "colourful",
    "favour", "favours", "favoured", "favouring", "favourite", "favourites",
    "honour", "honours", "honoured", "honouring", "honourable",
    "labour", "labours", "laboured", "labouring", "neighbour", "neighbours",
    "behaviour", "behaviours", "flavour", "flavours", "humour", "rumour", "rumours",
    "centre", "centres", "centred", "centring", "metre", "metres", "litre", "litres",
    "theatre", "theatres", "fibre", "fibres", "analyse", "analyses", "analysed", "analysing",
    "organise", "organises", "organised", "organising", "organisation", "organisations",
    "recognise", "recognises", "recognised", "recognising",
    "realise", "realises", "realised", "realising",
    "licence", "licences", "defence", "defences", "offence", "offences",
    "practise", "practises", "practised", "practising", "travelling", "travelled",
    "cancelled", "cancelling", "labelled", "labelling", "modelling", "modelled",
})
_TECHNICAL_WORDS = frozenset({
    "apis", "backend", "frontend", "metadata", "async", "runtime", "webhook",
    "webhooks", "docx", "pdf", "json", "yaml", "markdown", "redis", "postgresql",
    "kubernetes", "docker", "nginx", "numpy", "pydantic", "fastapi", "typescript",
    "javascript", "tokenizer", "tokenizers", "embeddings",
})


@dataclass(frozen=True)
class EnglishFinding:
    start: int
    end: int
    suggestion: str | None
    alternatives: tuple[str, ...]
    rule_id: str
    confidence: float


def preserve_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original.istitle():
        return replacement.capitalize()
    return replacement


@lru_cache(maxsize=1)
def _dictionary() -> SpellChecker:
    # Read-only shared dictionary: request-specific terms never mutate it.
    return SpellChecker(language="en", distance=1)


@lru_cache(maxsize=2048)
def _candidates(word: str) -> tuple[str, ...]:
    dictionary = _dictionary()
    if word in dictionary or word in _DIALECT_WORDS or word in _TECHNICAL_WORDS:
        return ()
    candidates = dictionary.candidates(word) or set()
    return tuple(sorted(
        (candidate for candidate in candidates if candidate != word),
        key=lambda candidate: (-dictionary.word_frequency[candidate], candidate),
    )[:3])


def spelling_findings(
    text: str, context: TextContext, curated: set[str],
) -> Iterator[EnglishFinding]:
    for match in _WORDS.finditer(text):
        word = match.group()
        if (context.is_protected(*match.span()) or not word.islower()
                or word in curated):
            continue
        candidates = _candidates(word)
        if not candidates:
            continue
        dictionary = _dictionary()
        first = dictionary.word_frequency[candidates[0]]
        second = dictionary.word_frequency[candidates[1]] if len(candidates) > 1 else 0
        confident = first >= 10 and first >= 5 * second
        yield EnglishFinding(
            *match.span(),
            candidates[0] if confident else None,
            candidates,
            "en_dictionary_spelling",
            0.8 if confident else 0.55,
        )


def grammar_findings(text: str, context: TextContext) -> Iterator[EnglishFinding]:
    for match in _SUBJECT_VERB.finditer(text):
        subject, verb = match.group(1).lower(), match.group(2).lower()
        if context.is_protected(*match.span()):
            continue
        replacements = (
            _SINGULAR if subject in {"he", "she", "it"} else
            {**_PLURAL, "is": "am", "are": "am", "was": "was"} if subject == "i" else
            _PLURAL
        )
        replacement = replacements.get(verb)
        if replacement is None or replacement == verb:
            continue
        yield EnglishFinding(
            *match.span(2), preserve_case(match.group(2), replacement), (),
            "en_subject_agreement", 0.85,
        )
