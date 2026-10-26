"""Hybrid retrieval primitive: vector (cosine) + BM25 (lexical), fused via
Reciprocal Rank Fusion, then reordered by a small cross-encoder reranker.

Used by ``catalog_engine`` for both retrieval stages (servers, then tools
within them) — this module is generic over "things with an embedding and
some text", it doesn't know which.

Why hybrid, why RRF, why a reranker
------------------------------------
Vector search catches paraphrases ("pending invoices" ~ "unpaid bills") but
is weak on exact/rare terms (a literal tool name, an ID, a jargon word not
well represented in the embedding). BM25 is the opposite: strong on exact
lexical overlap, blind to paraphrase. Combining both covers more queries
than either alone.

Reciprocal Rank Fusion combines the two rankings by *rank position*, not
raw score — cosine similarity (0..1) and BM25 (unbounded, corpus-dependent)
aren't on comparable scales, so fusing them by rank sidesteps normalization
entirely. This is the same approach Elasticsearch/Azure AI Search default to.

The cross-encoder reranker runs last, only over the fused shortlist (not
the whole candidate set) — it jointly encodes (query, document) for a much
more accurate relevance judgment than either signal alone, at the cost of
one forward pass per shortlisted candidate. Model: a ~80MB ONNX MiniLM
cross-encoder via ``fastembed`` (CPU-only, no torch/CUDA dependency chain).

Every signal degrades gracefully: missing embeddings, no lexical overlap,
or a reranker that fails to load all fall back to the next-best available
ranking rather than raising — worst case is the candidates in their
original (e.g. alphabetical) order.
"""
from __future__ import annotations

import difflib
import logging
import re
from functools import lru_cache
from typing import Callable, Optional, TypeVar

logger = logging.getLogger("user.hybrid_search")

T = TypeVar("T")

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Similarity ratio (difflib.SequenceMatcher, 0..1) above which a query token
# not found in the corpus vocabulary is treated as a typo of the closest
# vocabulary word rather than a genuinely different word. Chosen from
# measured ratios: real typos ("ceate"/"create" 0.91, "serach"/"search"
# 0.83, "mesage"/"message" 0.92) cluster at 0.83+; unrelated same-length
# words ("get"/"set" 0.67, "create"/"delete" 0.50) sit well below it.
_TYPO_MATCH_CUTOFF = 0.8

# ~80MB ONNX cross-encoder, CPU-only — see fastembed's TextCrossEncoder.
_RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
# How many fused candidates the reranker sees; the top_k returned may be
# smaller than this — reranking a wider shortlist than top_k catches cases
# where RRF's fused order and the cross-encoder's judgment disagree near
# the cutoff.
_RERANK_SHORTLIST_SIZE = 20

# How much the reranker's own ranking counts in the final RRF fusion,
# relative to the vector+BM25 fused ranking (weight 1.0). A small
# general-purpose cross-encoder trained on natural-language passages
# (MS-MARCO) is noticeably less reliable on terse, imperative-mood
# tool/API descriptions than on the prose it was trained on — verified
# live: it has twice ranked a clearly-relevant tool (a WhatsApp send and a
# Notion create-page tool) below unrelated ones, scoring the *wrong* tool
# highest with real, non-trivial confidence. 0.5 wasn't low enough to
# recover from that specific case (worked through the RRF arithmetic: at
# k=60 with the reranker one shortlist position out of step from
# vector+BM25's answer, its vote stays decisive until well under ~0.33);
# 0.3 was chosen with that margin, verified to flip the wrong order back.
# It still functions as a genuine second opinion (tipping close calls, or
# mattering when vector and BM25 disagree with each other) without being
# able to override vector+BM25 agreement the way a higher weight can.
_RERANK_WEIGHT = 0.3

# Tool/server text is short (a name, a one-line description, a few param
# names) — a single stopword match (e.g. query "..." sharing only "in" or
# "for" with a doc) is enough to make BM25 treat an irrelevant document as
# a lexical hit. Filtered out rather than left to IDF alone: with only a
# handful of candidate documents per query, corpus-wide IDF statistics
# aren't reliable enough to discount common words on their own.
_STOPWORDS = frozenset(
    "a an the this that these those is are was were be been being "
    "i you he she it we they my your his her its our their "
    "in on at for to of and or but if then else so as by with without "
    "from into onto up down out about over under again further "
    "do does did doing will would shall should can could may might must "
    "not no nor only own same than too very just".split()
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOPWORDS]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = (sum(x * x for x in a)) ** 0.5
    nb = (sum(y * y for y in b)) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# Minimum token length eligible for compound-split / substring matching
# (below). A short token ("at", "app") would trivially appear inside or
# alongside half the vocabulary, turning this into noise rather than a
# real signal — 4 chars keeps it to genuinely distinctive words.
_SUBSTRING_MATCH_MIN_LEN = 4


def _split_compound(token: str, vocabulary: set[str]) -> Optional[list[str]]:
    """If ``token`` is the exact concatenation of two vocabulary words
    (e.g. query "filesystem" against a corpus that only ever writes "file
    system" as two words), return those two words so BM25 credits both.

    Without this, a compound-vs-spaced mismatch contributes *zero*
    lexical signal even though a human reading "filesystem" next to "file
    system tools" would obviously call them the same thing — and unlike a
    misspelling, edit-distance typo correction can't catch it (the two
    spellings differ by exactly one space, which tanks the character-level
    similarity ratio well below the typo cutoff).
    """
    for i in range(_SUBSTRING_MATCH_MIN_LEN, len(token) - _SUBSTRING_MATCH_MIN_LEN + 1):
        left, right = token[:i], token[i:]
        if left in vocabulary and right in vocabulary:
            return [left, right]
    return None


def _substring_match(token: str, vocabulary: set[str]) -> Optional[str]:
    """The longest vocabulary word that ``token`` contains, or that
    contains ``token``, as a whole substring — catches an
    abbreviation/expansion mismatch exact-token BM25 matching misses
    (query "wikipedia" vs a server literally named "wiki"). Like
    :func:`_split_compound`, this is a different failure mode from a
    misspelling: "wikipedia" and "wiki" are genuinely different-length
    words, not typos of each other, so their edit-distance ratio sits well
    below the typo cutoff by design.

    Guarded by ``_SUBSTRING_MATCH_MIN_LEN`` on the shorter side so a short
    token doesn't spuriously "contain-match" half the vocabulary.
    """
    if len(token) < _SUBSTRING_MATCH_MIN_LEN:
        return None
    best: Optional[str] = None
    for word in vocabulary:
        shorter, longer = (word, token) if len(word) <= len(token) else (token, word)
        if len(shorter) < _SUBSTRING_MATCH_MIN_LEN:
            continue
        if shorter in longer and (best is None or len(word) > len(best)):
            best = word
    return best


def _correct_typos(query_tokens: list[str], vocabulary: set[str]) -> list[str]:
    """Fuzzy-correct query tokens against the candidate corpus's own
    vocabulary before BM25 lookup.

    BM25 only ever matches *exact* tokens — a single misspelled content
    word ("ceate" for "create") means that word contributes nothing at
    all, which can silently drop the entire lexical signal for an
    otherwise-matching document (verified live: "ceate notion page..."
    scored zero lexical overlap with the actual create-page tool). Generic
    by construction — it corrects against whatever vocabulary the current
    candidates' own text happens to contain, not a fixed dictionary, so it
    needs no per-word or per-vendor rules.

    A token already in the vocabulary is used as-is (exact match is always
    preferred over a fuzzy guess). An absent token is corrected by, in
    order: the closest vocabulary word above ``_TYPO_MATCH_CUTOFF`` (a
    likely misspelling); else an exact two-word compound split (a likely
    spacing difference, see :func:`_split_compound`); else a substring
    match (a likely abbreviation/expansion, see :func:`_substring_match`).
    Failing all three, it's left alone rather than risk conflating two
    genuinely different words.
    """
    corrected = []
    for token in query_tokens:
        if token in vocabulary:
            corrected.append(token)
            continue
        typo_match = difflib.get_close_matches(
            token, vocabulary, n=1, cutoff=_TYPO_MATCH_CUTOFF
        )
        if typo_match:
            corrected.append(typo_match[0])
            continue
        compound = _split_compound(token, vocabulary)
        if compound:
            corrected.extend(compound)
            continue
        substring = _substring_match(token, vocabulary)
        corrected.append(substring if substring else token)
    return corrected


def _bm25_rank_indices(query: str, texts: list[str]) -> list[int]:
    """Rank indices into ``texts`` by BM25 lexical relevance to ``query``,
    best first. Returns ``[]`` when there's no lexical overlap at all
    (every document scores 0) rather than an arbitrary tie order — an empty
    list means "this signal contributed nothing", so RRF fusion doesn't get
    polluted by a meaningless order over irrelevant documents.
    """
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        logger.warning("rank_bm25 not installed; skipping lexical ranking")
        return []
    tokenized = [_tokenize(t) for t in texts]
    if not any(tokenized):
        return []
    bm25 = BM25Okapi(tokenized)
    # rank_bm25 floors *negative* idf (a term in most documents) to a small
    # positive epsilon, but leaves an exact-zero idf unpatched. Zero happens
    # whenever a term's document frequency is precisely half the corpus
    # size (idf's log ratio hits log(1) = 0) — with the small candidate
    # pools typical here (a handful of servers, or one server's tool list),
    # that's common enough to silently zero out a real lexical match
    # rather than the "no signal at all" it looks like.
    eps = bm25.epsilon * bm25.average_idf
    for word, value in bm25.idf.items():
        if value == 0:
            bm25.idf[word] = eps

    vocabulary = set(bm25.idf.keys())
    query_tokens = _correct_typos(_tokenize(query), vocabulary)
    scores = bm25.get_scores(query_tokens)
    order = [i for i in range(len(texts)) if scores[i] > 0]
    order.sort(key=lambda i: scores[i], reverse=True)
    return order


def _rrf_fuse(
    rankings: list[list[int]],
    *,
    size: int,
    k: int = 60,
    weights: Optional[list[float]] = None,
) -> list[int]:
    """Reciprocal Rank Fusion of several best-first index rankings into one.
    ``k=60`` is the standard constant from the original RRF paper — it
    controls how quickly a ranking's contribution decays with rank; the
    result is insensitive to the exact value in practice. Indices absent
    from every ranking keep a fused score of 0 and fall to the tail in
    their original relative order (``sorted`` is stable).

    ``weights`` (default: 1.0 for every ranking) scales each ranking's
    contribution before summing — a ranking with weight 0.5 needs roughly
    twice the rank advantage to outweigh a weight-1.0 ranking. Used to make
    the cross-encoder rerank a *lighter* vote than vector+BM25 rather than
    an equal or overriding one — see ``_RERANK_WEIGHT``.
    """
    if weights is None:
        weights = [1.0] * len(rankings)
    scores = [0.0] * size
    for weight, ranking in zip(weights, rankings):
        for rank, idx in enumerate(ranking):
            scores[idx] += weight / (k + rank + 1)
    return sorted(range(size), key=lambda i: scores[i], reverse=True)


@lru_cache
def _get_reranker():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=_RERANK_MODEL)


def _rerank_scores(query: str, texts: list[str]) -> Optional[list[float]]:
    """Cross-encoder relevance scores for ``texts`` against ``query``, same
    order as ``texts``. Returns ``None`` (not a list of zeros) on any
    failure — e.g. the model can't be downloaded on first use — so the
    caller falls back to the fused rank order instead of treating
    "reranker unavailable" the same as "everything equally irrelevant".
    """
    if not texts:
        return []
    try:
        return list(_get_reranker().rerank(query, texts))
    except Exception:
        logger.warning(
            "cross-encoder rerank unavailable, using fused rank order", exc_info=True
        )
        return None


def _apply_relevance_floor(
    order: list[int], *, bm25_matched: set[int], top_k: int
) -> list[int]:
    """Trim the tail of ``order`` (best-first indices) to ``top_k``, but
    when at least one candidate in this ranking call has real lexical
    (BM25) evidence, also drop any trailing candidate ranked *after* the
    last BM25-matched one that itself has zero BM25 evidence — instead of
    always forcing exactly ``top_k`` results regardless of whether the
    tail candidates cleared any real relevance bar.

    Why: when the corpus text is generic/interchangeable (e.g. every
    candidate merely described as "<name> tools"), the vector signal alone
    often can't reliably separate a genuine match from an unrelated
    candidate that just happens to embed nearby, and a fixed slot count
    silently fills with noise (verified live: a 4-intent query correctly
    BM25-matched exactly 4 servers, but the unfilled 5th slot kept going
    to an unrelated server on vector-score noise alone — the two scores
    were 0.011 apart, well within that noise). A candidate ranked *between*
    two BM25-matched ones is left in place (it's genuinely competitive,
    not tail noise) — only the trailing run past the last real match is
    cut.

    Deliberately a no-op when BM25 found *no* matches at all for this
    call (``bm25_matched`` empty) — that's the genuine "vector caught a
    paraphrase BM25 has zero lexical overlap with" case hybrid search
    exists for, and it's left fully alone (existing pure-vector-ranked
    behavior, unchanged).
    """
    window = order[:top_k]
    if not bm25_matched:
        return window
    last_matched = max((i for i, idx in enumerate(window) if idx in bm25_matched), default=-1)
    return window[: last_matched + 1] if last_matched >= 0 else window


def rank(
    items: list[T],
    *,
    query: str,
    query_vector: Optional[list[float]],
    top_k: int,
    text_of: Callable[[T], str],
    embedding_of: Callable[[T], Optional[list[float]]],
    dim_of: Callable[[T], Optional[int]],
) -> list[T]:
    """Hybrid-rank ``items`` against ``query``: vector similarity + BM25,
    fused via RRF, then cross-encoder reranked for the final order.

    ``text_of``/``embedding_of``/``dim_of`` are accessors rather than
    assuming a fixed shape, so the same function ranks both
    ``VendorMCPServer`` and ``MCPTool`` rows.
    """
    if not items:
        return []
    n = len(items)
    texts = [text_of(it) for it in items]

    rankings: list[list[int]] = []
    if query_vector is not None:
        scored = [
            (cosine_similarity(query_vector, embedding_of(it)), idx)
            for idx, it in enumerate(items)
            if embedding_of(it) and dim_of(it) == len(query_vector)
        ]
        if scored:
            scored.sort(key=lambda s: s[0], reverse=True)
            rankings.append([idx for _, idx in scored])

    bm25_order: list[int] = []
    if query:
        bm25_order = _bm25_rank_indices(query, texts)
        if bm25_order:
            rankings.append(bm25_order)
    bm25_matched = set(bm25_order)

    if not rankings:
        return items[:top_k]

    fused = _rrf_fuse(rankings, size=n)

    if not query:
        return [items[i] for i in fused[:top_k]]

    shortlist_size = max(top_k, _RERANK_SHORTLIST_SIZE)
    shortlist = fused[:shortlist_size]
    rerank_scores = _rerank_scores(query, [texts[i] for i in shortlist])

    if rerank_scores is None:
        floored = _apply_relevance_floor(fused, bm25_matched=bm25_matched, top_k=top_k)
        return [items[i] for i in floored]

    rerank_order = [
        shortlist[i]
        for i, _ in sorted(enumerate(rerank_scores), key=lambda p: p[1], reverse=True)
    ]
    # Fuse the reranker's ranking of the shortlist back into the existing
    # vector+BM25 fused order via RRF, rather than letting it unilaterally
    # replace that order. A general-purpose passage cross-encoder wasn't
    # trained on terse tool/API metadata text, so on a middling/ambiguous
    # case its absolute scores can be noisy — treating it as one more vote
    # (not a veto) means a confident vector+BM25 agreement isn't flipped by
    # a low-confidence reranker score. Weighted below 1.0 (see
    # _RERANK_WEIGHT) — verified against two real regressions where the
    # reranker was outright wrong with real confidence, not just noisy:
    # flipping a correct "create_issue" vs "list_pull_requests" match for a
    # bug-report query, and ranking a "move page" tool above the actual
    # "create page" tool for a create-page query.
    final = _rrf_fuse([fused, rerank_order], size=n, weights=[1.0, _RERANK_WEIGHT])
    floored = _apply_relevance_floor(final, bm25_matched=bm25_matched, top_k=top_k)
    return [items[i] for i in floored]


__all__ = ["rank", "cosine_similarity"]
