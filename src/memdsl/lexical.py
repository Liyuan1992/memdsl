"""Shared deterministic lexical tokenization for indexed query retrieval."""

from __future__ import annotations

import re
from typing import List


QUERY_WORD_RE = re.compile(r"[a-z0-9_]+")

QUERY_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "of",
    "to", "in", "on", "at", "for", "and", "or", "not", "no", "my",
    "me", "i", "it", "its", "this", "that", "these", "those", "do",
    "does", "did", "how", "what", "when", "where", "which", "who",
    "why", "should", "would", "could", "can", "will", "with", "about",
    "into", "over", "please", "help", "going", "keep", "get", "make",
    "your", "you", "we", "our", "us", "if", "so", "as", "by", "from",
    "up", "out", "any",
})


def query_terms(text: str) -> List[str]:
    """Return normalized non-stopword terms while preserving input order."""
    return [
        term for term in QUERY_WORD_RE.findall(str(text or "").lower())
        if term not in QUERY_STOPWORDS
    ]
