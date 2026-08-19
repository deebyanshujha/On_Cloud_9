"""Comorbidity-vs-drug-label context checking (TheraLens phase).

Scope, explicitly (per the brief): this checks a *candidate drug's* label
text (contraindications/warnings) against a case's comorbidity terms. It
does NOT attempt current-medication pairwise drug-drug interaction checking
— that needs one drug's label to explicitly name the other drug, which is a
harder problem deferred for a later phase (see PROGRESS.md "Known
limitations").

Reuses `app/core/disease_matching.py`'s token-subset matching — this is the
same "does this disease term appear in this drug-label paragraph" problem
already solved there for indications_and_usage, just applied to
contraindications/warnings text instead.

Three-state result per comorbidity, chosen deliberately (not a boolean) so
absence of evidence is never conflated with evidence of absence:

- "conflict_detected": the drug has contraindications/warnings text, and the
  comorbidity's tokens appear in it. Evidence: the actual matching sentence,
  quoted verbatim from the real label text — never fabricated.
- "no_conflict_detected": the drug HAS contraindications/warnings text (so a
  check was actually possible), and the comorbidity's tokens do NOT appear
  in it.
- "insufficient_evidence": the drug has no contraindications/warnings text
  at all (openFDA didn't return the field for any of its ingested labels),
  so there is nothing to check against. Distinct from "no conflict" — we
  genuinely don't know, we didn't check-and-clear.
"""
from __future__ import annotations

from typing import Literal, Optional

from app.core.disease_matching import disease_tokens, is_too_generic_to_match

ConflictState = Literal["conflict_detected", "no_conflict_detected", "insufficient_evidence"]

_SENTENCE_SPLIT_RE = None  # set below, avoids importing re twice for readability


def _split_sentences(text: str) -> list[str]:
    import re

    global _SENTENCE_SPLIT_RE
    if _SENTENCE_SPLIT_RE is None:
        _SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _find_matching_sentence(comorbidity_tokens: set[str], text: str) -> Optional[str]:
    """Returns the first real sentence from `text` whose tokens are a
    superset of `comorbidity_tokens`, so the evidence quoted back is always
    a verbatim excerpt of actual label text. Falls back to the whole text
    if the match spans multiple sentences (still real text, just less
    precisely scoped) — this can happen with list-formatted label sections
    where a condition name and its consequence are split by list markers
    that aren't sentence punctuation."""
    for sentence in _split_sentences(text):
        if comorbidity_tokens.issubset(disease_tokens(sentence)):
            return sentence
    return None


def check_comorbidity_conflict(
    comorbidity: str,
    contraindications: Optional[str],
    warnings: Optional[str],
) -> tuple[ConflictState, Optional[str]]:
    """Checks one comorbidity term against one drug label's
    contraindications + warnings text. Returns (state, evidence_text).
    evidence_text is populated only for "conflict_detected", and is always a
    verbatim excerpt of the real label text passed in — never generated."""
    fields = [t for t in (contraindications, warnings) if t]
    if not fields:
        return "insufficient_evidence", None

    comorbidity_tokens = disease_tokens(comorbidity, strip_qualifiers=True)
    if not comorbidity_tokens or is_too_generic_to_match(comorbidity_tokens):
        return "insufficient_evidence", None

    for field_text in fields:
        if comorbidity_tokens.issubset(disease_tokens(field_text)):
            evidence = _find_matching_sentence(comorbidity_tokens, field_text) or field_text
            return "conflict_detected", evidence

    return "no_conflict_detected", None


# One state is more informative than another when a drug has multiple
# ingested labels (multiple branded/generic products) with different text.
# Priority when combining per-label results into one per-drug result: a
# real conflict found anywhere always wins; a clean check on at least one
# label beats having no data at all.
_STATE_PRIORITY = {"conflict_detected": 2, "no_conflict_detected": 1, "insufficient_evidence": 0}


def combine_states(results: list[tuple[ConflictState, Optional[str]]]) -> tuple[ConflictState, Optional[str]]:
    """Combines per-label (state, evidence) results for the same drug into
    one overall result, per the priority documented above. If no results
    were given at all (drug has zero ingested labels), returns
    insufficient_evidence."""
    if not results:
        return "insufficient_evidence", None
    return max(results, key=lambda r: _STATE_PRIORITY[r[0]])
