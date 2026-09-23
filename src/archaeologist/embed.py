"""Week 4: embedders, behind an interface small enough to swap.

The default is lexical, on purpose
----------------------------------
The default embedder is a pure-Python TF-IDF vectoriser with cosine
similarity. It needs no new dependency, downloads nothing, and gives the same
ranking for the same input every time.

That is a deliberate trade, not a claim that it is as good as a neural model.
It is not. TF-IDF matches *words*: it knows "updated" and "update" are close
only because of a crude suffix stripper below, and it has no idea that
"billing" and "invoice" are related. A sentence-transformer would handle both.
On true semantic matching, lexical similarity is weaker, full stop.

What the trade buys:

* **CI never downloads a model.** The deterministic half of this project runs
  on every pull request in under a second (Week 5). A 90 MB model download and
  a torch install would end that.
* **Retrieval evals can be exact.** The interesting part of Week 4 is the
  *fusion* of graph and vector results. With a deterministic embedder that
  fusion can be asserted on in tier 1, like any other fact. With a neural one
  the ranking drifts across library versions and hardware.
* **The architecture is embedder-agnostic.** The retriever only sees the
  ``Embedder`` protocol. Swapping in ``SentenceTransformerEmbedder`` is a flag,
  and nothing else changes.

Storage is in memory, rebuilt from the catalog on each run. For TF-IDF over a
few thousand cards that costs milliseconds. A neural embedder would want a
cache (a SQLite table keyed by card hash is the obvious one). That isn't built
because nothing needs it yet. No vector database: at org scale (thousands of
artifacts, not millions) brute-force cosine is fast enough, and one less
service is one less thing to run.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    """What the retriever needs from an embedder, and nothing more.

    ``fit`` exists because corpus-statistics embedders (TF-IDF) need to see the
    documents first. Pretrained models can make it a no-op. Queries and
    documents are embedded separately because some neural models encode them
    differently (query prefixes, asymmetric models).
    """

    name: str

    def fit(self, documents: Sequence[str]) -> None: ...

    def embed_documents(self, documents: Sequence[str]) -> list[Any]: ...

    def embed_query(self, text: str) -> Any: ...

    def similarity(self, a: Any, b: Any) -> float: ...


# --------------------------------------------------------------------------
# Tokenising
# --------------------------------------------------------------------------

_STOPWORDS = frozenset("""
a an and any are as at be by can do does for from has have how i if in into is
it its me my no not of on or so that the their them then there these this to
was what when where which who why will with would you your
""".split())

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")


def _stem(token: str) -> str:
    """A deliberately crude suffix stripper: update/updated/updates/updating
    all become ``updat``.

    Not Porter, not Snowball. Good enough to join inflections of the same verb
    in a small corpus. It will occasionally join words that aren't related,
    which on a few dozen short cards costs less than missing the obvious ones.
    """
    for suffix in ("ing", "ed", "es", "s", "e"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    """Split on punctuation and camelCase, lowercase, drop stopwords and
    single characters (the ``c`` left over from ``__c``), stem."""
    tokens: list[str] = []
    for chunk in _SPLIT_RE.split(text):
        for part in _CAMEL_RE.split(chunk):
            token = part.lower()
            if len(token) < 2 or token in _STOPWORDS:
                continue
            tokens.append(_stem(token))
    return tokens


# --------------------------------------------------------------------------
# TF-IDF: the default
# --------------------------------------------------------------------------

SparseVector = dict[str, float]


class TfidfEmbedder:
    """Sparse TF-IDF with sublinear term frequency and smoothed IDF.

    Vectors are ``{term: weight}`` dicts, L2-normalised, so cosine is a dot
    product over the shared terms. Dense vectors over a real org's vocabulary
    would be tens of thousands of mostly-zero floats per card, in pure Python.
    """

    name = "tfidf"

    def __init__(self) -> None:
        self._idf: dict[str, float] = {}

    def fit(self, documents: Sequence[str]) -> None:
        n = len(documents)
        df: Counter[str] = Counter()
        for doc in documents:
            df.update(set(tokenize(doc)))
        # Smoothed IDF, as in scikit-learn: a term in every document still
        # gets weight 1, not 0, so "lead" isn't erased from a Lead-heavy org.
        self._idf = {
            term: math.log((1 + n) / (1 + count)) + 1.0 for term, count in df.items()
        }

    def _vector(self, text: str) -> SparseVector:
        counts = Counter(t for t in tokenize(text) if t in self._idf)
        vec = {
            term: (1.0 + math.log(tf)) * self._idf[term] for term, tf in counts.items()
        }
        norm = math.sqrt(sum(w * w for w in vec.values()))
        return {t: w / norm for t, w in vec.items()} if norm else {}

    def embed_documents(self, documents: Sequence[str]) -> list[SparseVector]:
        return [self._vector(d) for d in documents]

    def embed_query(self, text: str) -> SparseVector:
        # Query terms the corpus has never seen carry no information about
        # which card to prefer, so they're dropped rather than guessed at.
        return self._vector(text)

    def similarity(self, a: SparseVector, b: SparseVector) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(w * b.get(t, 0.0) for t, w in a.items())


# --------------------------------------------------------------------------
# Neural: optional, never on the default path
# --------------------------------------------------------------------------

class SentenceTransformerEmbedder:
    """Local neural embeddings via ``sentence-transformers``.

    Imported lazily, inside ``__init__``, so importing this module never pulls
    in torch. Used only when explicitly selected (``ask --embedder st``) and
    installed via ``requirements-llm.txt``. Tests never construct it.
    """

    name = "sentence-transformers"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Install requirements-llm.txt, or use the default tfidf embedder."
            ) from exc
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    def fit(self, documents: Sequence[str]) -> None:
        return None

    def embed_documents(self, documents: Sequence[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in
                self._model.encode(list(documents), normalize_embeddings=True)]

    def embed_query(self, text: str) -> list[float]:
        return list(map(float, self._model.encode([text], normalize_embeddings=True)[0]))

    def similarity(self, a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))


EMBEDDERS = {"tfidf": TfidfEmbedder, "st": SentenceTransformerEmbedder}


def get(name: str = "tfidf") -> Embedder:
    try:
        factory = EMBEDDERS[name]
    except KeyError:
        raise ValueError(f"unknown embedder {name!r} (expected one of {sorted(EMBEDDERS)})")
    return factory()
