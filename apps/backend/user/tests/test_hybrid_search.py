"""Unit tests for the hybrid (vector + BM25 + rerank) retrieval primitive.

The reranker (``fastembed``) is mocked throughout — it needs a model
download on first use, which has no place in a fast/deterministic unit
suite. Two of these tests are regression tests for real issues found while
manually verifying this module against live embeddings before it shipped:

* BM25 matching only a stopword (e.g. query and one document both happen
  to contain "in") and treating that as a real lexical hit.
* The reranker's raw score fully overriding a confident, correct
  vector-similarity order on a case where its own scores were low-margin
  noise (a general passage cross-encoder wasn't trained on terse
  tool/API metadata text, so it isn't always confident on this text style).
"""
from __future__ import annotations

from unittest.mock import patch

from user.services import hybrid_search as hs


class Doc:
    def __init__(self, name: str, embedding=None, dim=None):
        self.name = name
        self.embedding = embedding
        self.dim = dim


def _rank(items, query, query_vector, top_k=10, rerank_scores=None):
    """Call hybrid_search.rank with the reranker mocked (or disabled)."""
    with patch.object(hs, "_rerank_scores", return_value=rerank_scores):
        return hs.rank(
            items,
            query=query,
            query_vector=query_vector,
            top_k=top_k,
            text_of=lambda d: d.name,
            embedding_of=lambda d: d.embedding,
            dim_of=lambda d: d.dim,
        )


class TestBM25:
    def test_ranks_by_lexical_overlap(self):
        # A 3rd, unrelated document keeps this from being the degenerate
        # case where every word is unique to one of only two documents
        # (idf is undefined/zero for all terms at once) — see
        # test_all_zero_idf_corpus_returns_empty below for that case.
        order = hs._bm25_rank_indices(
            "create a github issue",
            [
                "create_issue github issue tracker",
                "get weather forecast city",
                "search vendor invoices by amount",
            ],
        )
        assert order == [0]

    def test_all_zero_idf_corpus_returns_empty(self):
        """A 2-document corpus where every word is unique to one document
        makes BM25's idf exactly 0 for every term (df == N/2 for all of
        them) — a real but narrow rank_bm25 edge case. No real signal
        exists to recover here (average_idf is itself 0), so this must
        degrade to "no lexical signal" rather than error or rank randomly.
        """
        order = hs._bm25_rank_indices(
            "create a github issue",
            ["create_issue github issue tracker", "get weather forecast city"],
        )
        assert order == []

    def test_no_overlap_returns_empty(self):
        assert hs._bm25_rank_indices("xyz", ["abc def", "ghi jkl"]) == []

    def test_stopword_only_overlap_is_ignored(self):
        """Regression: query and doc sharing only a stopword ('in') must
        not register as a lexical match — this previously let BM25 rank an
        irrelevant document above genuinely relevant ones that share zero
        content words with the query."""
        order = hs._bm25_rank_indices(
            "will it rain in mumbai this week",
            ["create issue in a repo", "get weather forecast for a city"],
        )
        assert order == []

    def test_tokenize_strips_stopwords(self):
        assert hs._tokenize("this is a repo for the weather") == ["repo", "weather"]

    def test_typo_in_query_still_matches(self):
        """Regression: 'ceate' (typo for 'create') previously scored zero
        lexical overlap with a create-page tool, even though every other
        word matched — a single misspelled content word silently dropped
        the entire BM25 signal for an otherwise-clear match."""
        order = hs._bm25_rank_indices(
            "ceate a page with title test",
            [
                "create a page in the specified database or as a child of an existing page",
                "search all pages and databases shared with the integration",
                "retrieve a page by its page id",
            ],
        )
        assert order[0] == 0

    def test_typo_correction_does_not_conflate_unrelated_words(self):
        """A query token with no close match in the corpus vocabulary (not
        just a misspelling of something present) must be left alone, not
        fuzzy-matched to an unrelated word that happens to be similar
        length."""
        assert hs._correct_typos(["weather"], {"create", "delete", "search"}) == [
            "weather"
        ]

    def test_typo_correction_prefers_exact_match_over_fuzzy(self):
        # "create" is itself in the vocabulary — must not get fuzzy-matched
        # to something else close by (e.g. a near-duplicate typo entry).
        assert hs._correct_typos(["create"], {"create", "crate"}) == ["create"]


class TestRRFFuse:
    def test_agreeing_rankings_reinforce(self):
        fused = hs._rrf_fuse([[0, 1, 2], [0, 2, 1]], size=3)
        assert fused[0] == 0  # ranked #1 in both

    def test_single_ranking_passthrough_order(self):
        assert hs._rrf_fuse([[2, 0, 1]], size=3) == [2, 0, 1]

    def test_missing_from_all_rankings_falls_to_tail(self):
        # index 2 never appears in either ranking -> fused score 0, stays last.
        fused = hs._rrf_fuse([[0, 1], [1, 0]], size=3)
        assert fused[-1] == 2

    def test_weights_default_to_equal(self):
        equal = hs._rrf_fuse([[0, 1], [1, 0]], size=2)
        explicit = hs._rrf_fuse([[0, 1], [1, 0]], size=2, weights=[1.0, 1.0])
        assert equal == explicit

    def test_lower_weight_reduces_a_ranking_s_influence(self):
        # Ranking A (weight 1.0) puts 0 first; ranking B (weight down-
        # weighted) puts 1 first. A full-weight B would tie/flip this; a
        # down-weighted B should not be able to overturn A's pick — this is
        # the mechanism the reranker's reduced weight relies on.
        fused = hs._rrf_fuse([[0, 1], [1, 0]], size=2, weights=[1.0, 0.5])
        assert fused[0] == 0


class TestRank:
    def test_no_candidates(self):
        assert _rank([], "q", None) == []

    def test_no_query_and_no_vector_returns_first_n(self):
        items = [Doc("a"), Doc("b"), Doc("c")]
        assert _rank(items, "", None, top_k=2) == items[:2]

    def test_vector_only_orders_by_cosine(self):
        items = [
            Doc("a", embedding=[1.0, 0.0], dim=2),
            Doc("b", embedding=[0.0, 1.0], dim=2),
        ]
        ranked = _rank(items, "q", [1.0, 0.0], rerank_scores=None)
        assert ranked[0].name == "a"

    def test_mismatched_embedding_dim_skipped(self):
        items = [Doc("a", embedding=[1.0, 0.0, 0.0], dim=3)]
        # query_vector has dim 2, item has dim 3 -> vector signal excluded;
        # no query text either, so falls back to original order.
        ranked = _rank(items, "", [1.0, 0.0])
        assert ranked == items

    def test_rerank_is_fused_not_overridden(self):
        """Regression: a vector ranking that confidently prefers 'a' over
        'b' must not be flipped by a reranker whose own score prefers 'b' —
        the two signals are combined via RRF, not overridden outright."""
        items = [
            Doc("a", embedding=[1.0, 0.0], dim=2),
            Doc("b", embedding=[0.0, 1.0], dim=2),
        ]
        # Reranker scores disagree with the (correct) vector order.
        ranked = _rank(items, "q", [1.0, 0.0], rerank_scores=[-9.0, -5.0])
        assert ranked[0].name == "a"

    def test_reranker_unavailable_keeps_fused_order(self):
        items = [
            Doc("a", embedding=[1.0, 0.0], dim=2),
            Doc("b", embedding=[0.0, 1.0], dim=2),
        ]
        ranked = _rank(items, "q", [1.0, 0.0], rerank_scores=None)
        assert ranked[0].name == "a"
