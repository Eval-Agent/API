"""
Ensemble concept-coverage scorer for deterministic partial-credit resolution.

Four signal pipeline:
  1. Lexical   — exact string + lemmatization match (spaCy)
  2. Semantic  — cosine similarity (sentence-transformers / all-MiniLM-L6-v2)
  3. NLI       — natural language inference entailment (cross-encoder/nli-MiniLM2-L6-H768)
  4. LLM       — Gemini verdict passed in as an external signal

Each signal produces a score in [0, 1] per concept keyword.
Scores are combined via weighted average → final coverage fraction.
If coverage >= KEYWORD_MATCH_THRESHOLD  → keyword_only  percentage is applied.
Otherwise                               → partial_explanation percentage is applied.

All heavy models are lazy-loaded and process-cached via @lru_cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import List

import numpy as np


# ---------------------------------------------------------------------------
# Weights for the ensemble
# ---------------------------------------------------------------------------

W_LEXICAL  = 0.25   # fast, zero variance — strong for exact terminology
W_SEMANTIC = 0.30   # catches paraphrases and synonyms
W_NLI      = 0.30   # checks logical entailment — strongest for conceptual coverage
W_LLM      = 0.15   # Gemini partial verdict as a soft prior

assert abs(W_LEXICAL + W_SEMANTIC + W_NLI + W_LLM - 1.0) < 1e-9, "Weights must sum to 1.0"

# Fraction of keywords whose ensemble score must meet KEYWORD_SCORE_MIN
# for the answer to be considered "keyword-present"
KEYWORD_MATCH_THRESHOLD = 0.5
KEYWORD_SCORE_MIN       = 0.5   # per-keyword ensemble score threshold

# Raw thresholds for individual signals
SEMANTIC_THRESHOLD   = 0.55
NLI_ENTAIL_THRESHOLD = 0.60


# ---------------------------------------------------------------------------
# Lazy model loaders
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_nlp():
    import spacy
    try:
        return spacy.load("en_core_web_sm")
    except OSError:
        from spacy.cli import download
        download("en_core_web_sm")
        return spacy.load("en_core_web_sm")


@lru_cache(maxsize=1)
def _get_encoder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")


@lru_cache(maxsize=1)
def _get_nli():
    from sentence_transformers import CrossEncoder
    return CrossEncoder("cross-encoder/nli-MiniLM2-L6-H768")


# ---------------------------------------------------------------------------
# Signal 1 — Lexical (exact + lemma)
# ---------------------------------------------------------------------------

def _lemmas(text: str, nlp) -> set[str]:
    doc = nlp(text.lower())
    return {t.lemma_ for t in doc if t.is_alpha and not t.is_stop}


def _lexical_score(keyword: str, answer_lemmas: set[str], nlp) -> float:
    """1.0 if any keyword lemma found in answer lemmas, else 0.0."""
    kw_lemmas = _lemmas(keyword, nlp)
    return 1.0 if kw_lemmas & answer_lemmas else 0.0


# ---------------------------------------------------------------------------
# Signal 2 — Semantic similarity
# ---------------------------------------------------------------------------

def _semantic_score(keyword: str, answer: str, encoder) -> float:
    """Cosine similarity between keyword and answer embeddings, clipped to [0, 1]."""
    vecs = encoder.encode([keyword, answer], convert_to_numpy=True)
    kv, av = vecs[0], vecs[1]
    denom = np.linalg.norm(kv) * np.linalg.norm(av)
    if denom == 0:
        return 0.0
    return float(np.clip(np.dot(kv, av) / denom, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Signal 3 — NLI entailment
# ---------------------------------------------------------------------------

def _nli_score(concept_description: str, answer: str, nli) -> float:
    """
    Uses NLI cross-encoder to check whether the answer entails the concept.
    The cross-encoder returns logits for [contradiction, entailment, neutral].
    We apply softmax and return the entailment probability.
    """
    logits = nli.predict([(answer, concept_description)])  # shape (1, 3)
    probs  = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)  # softmax
    return float(probs[0][1])   # index 1 = entailment


# ---------------------------------------------------------------------------
# Signal 4 — LLM (Gemini verdict passed in)
# ---------------------------------------------------------------------------

def _llm_score(llm_verdict: str) -> float:
    """
    Convert the Gemini verdict into a soft prior score.
      correct   → 1.0
      partial   → 0.5
      incorrect → 0.0
    """
    return {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}.get(llm_verdict.lower(), 0.5)


# ---------------------------------------------------------------------------
# Per-keyword ensemble score
# ---------------------------------------------------------------------------

@dataclass
class KeywordSignals:
    keyword:  str
    lexical:  float
    semantic: float
    nli:      float
    llm:      float
    ensemble: float
    matched:  bool


def _score_keyword(
    keyword: str,
    concept_description: str,
    answer: str,
    answer_lemmas: set[str],
    llm_verdict: str,
    nlp,
    encoder,
    nli,
) -> KeywordSignals:
    lex  = _lexical_score(keyword, answer_lemmas, nlp)
    sem  = _semantic_score(keyword, answer, encoder)
    nli_ = _nli_score(concept_description, answer, nli)
    llm  = _llm_score(llm_verdict)

    ensemble = (
        W_LEXICAL  * lex  +
        W_SEMANTIC * sem  +
        W_NLI      * nli_ +
        W_LLM      * llm
    )

    return KeywordSignals(
        keyword=keyword,
        lexical=round(lex,  4),
        semantic=round(sem, 4),
        nli=round(nli_,     4),
        llm=round(llm,      4),
        ensemble=round(ensemble, 4),
        matched=ensemble >= KEYWORD_SCORE_MIN,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class ConceptCoverageResult:
    keywords_matched:  int
    keywords_total:    int
    coverage_fraction: float
    keyword_present:   bool          # True  → use keyword_only_percentage
                                     # False → use partial_explanation_percentage
    signals: List[KeywordSignals]


def score_concept_coverage(
    keywords: List[str],
    concept_description: str,
    answer_text: str,
    llm_verdict: str,
) -> ConceptCoverageResult:
    """
    Runs the 4-signal ensemble for every rubric keyword and returns a
    ConceptCoverageResult indicating whether keyword-level credit applies.

    Only called when Gemini verdict is "partial". For "correct" / "incorrect"
    the caller applies full / zero marks directly without running this.
    """
    if not keywords or not answer_text.strip():
        return ConceptCoverageResult(
            keywords_matched=0,
            keywords_total=len(keywords),
            coverage_fraction=0.0,
            keyword_present=False,
            signals=[],
        )

    nlp     = _get_nlp()
    encoder = _get_encoder()
    nli     = _get_nli()

    answer_lemmas = _lemmas(answer_text, nlp)

    signal_results = [
        _score_keyword(kw, concept_description, answer_text, answer_lemmas, llm_verdict, nlp, encoder, nli)
        for kw in keywords
    ]

    matched  = sum(1 for s in signal_results if s.matched)
    total    = len(keywords)
    fraction = matched / total if total > 0 else 0.0

    return ConceptCoverageResult(
        keywords_matched=matched,
        keywords_total=total,
        coverage_fraction=round(fraction, 4),
        keyword_present=fraction >= KEYWORD_MATCH_THRESHOLD,
        signals=signal_results,
    )