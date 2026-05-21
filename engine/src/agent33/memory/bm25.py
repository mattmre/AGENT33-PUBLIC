"""BM25 scoring engine for keyword-based document retrieval.

Implements the Okapi BM25 ranking function for term-frequency-based
search over an in-memory corpus.  Used alongside pgvector semantic
search to provide hybrid retrieval.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

# ── Stop-words (top-50 English) ─────────────────────────────────────

_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "my",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "she",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "you",
    }
)


@dataclass
class BM25Result:
    """A single BM25 search result."""

    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    doc_index: int = 0


def tokenize(text: str, *, remove_stopwords: bool = True) -> list[str]:
    """Tokenize text into lowercase alphanumeric tokens.

    Optionally removes common English stop-words to improve relevance.
    """
    tokens = re.findall(r"\w+", text.lower())
    if remove_stopwords:
        tokens = [t for t in tokens if t not in _STOP_WORDS]
    return tokens


class BM25Index:
    """In-memory BM25 index for keyword-based document retrieval.

    Parameters
    ----------
    k1:
        Term-frequency saturation parameter (default 1.2).
    b:
        Length-normalization parameter (default 0.75).
    """

    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        # Corpus storage
        self._docs: list[tuple[str, dict[str, Any]]] = []
        self._tokenized: list[list[str]] = []
        self._doc_lens: list[int] = []
        # IDF data
        self._doc_freqs: dict[str, int] = {}
        self._n: int = 0
        self._avgdl: float = 0.0

    # ── Corpus building ──────────────────────────────────────────────

    def add_document(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Add a document to the index.  Returns the document index."""
        tokens = tokenize(content)
        doc_idx = self._n
        self._docs.append((content, metadata or {}))
        self._tokenized.append(tokens)
        self._doc_lens.append(len(tokens))
        self._n += 1

        # Update document frequency counts (each unique term in the doc).
        for term in set(tokens):
            self._doc_freqs[term] = self._doc_freqs.get(term, 0) + 1

        # Recompute average document length.
        self._avgdl = sum(self._doc_lens) / self._n
        return doc_idx

    def add_documents(
        self,
        documents: list[tuple[str, dict[str, Any] | None]],
    ) -> list[int]:
        """Bulk-add documents.  Returns list of document indices."""
        return [self.add_document(text, meta) for text, meta in documents]

    @property
    def size(self) -> int:
        """Number of documents in the index."""
        return self._n

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 5) -> list[BM25Result]:
        """Score all documents against *query* and return top-k results."""
        if self._n == 0:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores: list[tuple[int, float]] = []
        for i in range(self._n):
            score = self._score_document(query_tokens, i)
            if score > 0:
                scores.append((i, score))

        scores.sort(key=lambda x: x[1], reverse=True)

        return [
            BM25Result(
                text=self._docs[idx][0],
                score=score,
                metadata=self._docs[idx][1],
                doc_index=idx,
            )
            for idx, score in scores[:top_k]
        ]

    # ── Internals ────────────────────────────────────────────────────

    def _idf(self, term: str) -> float:
        """Inverse document frequency for *term*."""
        n = self._doc_freqs.get(term, 0)
        if n == 0:
            return 0.0
        return math.log((self._n - n + 0.5) / (n + 0.5) + 1.0)

    def _score_document(self, query_tokens: list[str], doc_idx: int) -> float:
        """BM25 score of document *doc_idx* against *query_tokens*."""
        doc_tokens = self._tokenized[doc_idx]
        doc_len = self._doc_lens[doc_idx]

        # Build term-frequency map for this document.
        tf_map: dict[str, int] = {}
        for token in doc_tokens:
            tf_map[token] = tf_map.get(token, 0) + 1

        score = 0.0
        for term in query_tokens:
            idf = self._idf(term)
            tf = tf_map.get(term, 0)
            if tf == 0:
                continue
            numerator = tf * (self._k1 + 1)
            denominator = tf + self._k1 * (
                1 - self._b + self._b * doc_len / max(self._avgdl, 1e-10)
            )
            score += idf * numerator / denominator
        return score

    def clear(self) -> None:
        """Remove all documents from the index."""
        self._docs.clear()
        self._tokenized.clear()
        self._doc_lens.clear()
        self._doc_freqs.clear()
        self._n = 0
        self._avgdl = 0.0
