"""Disease-name normalization/matching (Step 5).

Exact string matching (the Step 2 placeholder) was proven insufficient by
real data pulled in Steps 3 and 4:

- False negative: the Step 2 fixture says "pancreatic cancer", but real
  ClinicalTrials.gov data lists the condition as "Stage IV Pancreatic
  Cancer" — same disease, a staging qualifier gets in the way of an exact
  match, so a real signal would silently be dropped.
- False positive risk: the fixture says "pulmonary hypertension", but
  openFDA's `indications_and_usage` for sildenafil (Revatio) is a whole
  paragraph that says "...pulmonary arterial hypertension...". Sildenafil
  genuinely IS approved for PAH (a pulmonary hypertension subtype) — an
  exact/substring match on the short phrase misses it, so the system would
  wrongly flag an already-approved use as a "new" signal.

Both cases are handled by the same rule: strip staging/qualifier words from
the *observed* disease mention, then check whether every remaining token
also appears somewhere in the *approved* text's tokens. Token-set
containment (rather than exact-string or exact-substring) is what lets a
short, general observed term ("pulmonary hypertension") match inside a
longer, more specific approved paragraph ("...pulmonary arterial
hypertension...") without us having to special-case "arterial".

This is a deliberately simple, non-ML heuristic — not ontology-aware
(MeSH/RxNorm). Two data-quality gaps were flagged (not silently papered
over) when Step 5 shipped, and are addressed here as two small, separate,
testable functions rather than folded into the core matching logic:

- `is_junk_condition`: Step 3's real pipeline run surfaced ClinicalTrials.gov
  "conditions" that aren't diseases at all — generic trial-eligibility
  terms ("healthy", "efficacy", "overweight") and, less commonly, whole
  sentences of study description text. Filtering these out before they
  reach the comparison step keeps junk out of the scored signal output.
- `is_too_generic_to_match`: guards the single-token false-positive risk
  originally flagged in `diseases_match` — a bare, very generic observed
  term like "cancer" could otherwise match against any approved text that
  happens to mention that word anywhere (e.g. an unrelated boxed-warning
  sentence).
"""
from __future__ import annotations

import re

# Staging/qualifier words that describe how advanced a disease is, not what
# the disease *is*. Stripped from the observed side only — see
# diseases_match's docstring for why they're deliberately not stripped from
# the approved side too.
STAGING_QUALIFIERS = {
    "stage",
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "vi",
    "metastatic",
    "recurrent",
    "advanced",
    "relapsed",
    "refractory",
    "unresectable",
    "localized",
    "grade",
}

_WORD_RE = re.compile(r"[a-z0-9]+")

# Apostrophe characters that show up in real disease names' possessive
# forms ("Alzheimer's", "Parkinson's", "Crohn's", "Sjogren's", ...) —
# straight ASCII, both curly/typographic quote directions, and the
# backtick/acute-accent look-alikes some sources use as a substitute.
# Stripped (deleted, not replaced with a space) before tokenizing so
# "Alzheimer's" and "Alzheimers" collapse to the exact same single token
# ("alzheimers") regardless of which form either side of a comparison
# happens to use — see disease_tokens()/strip_punctuation_variants().
_APOSTROPHE_RE = re.compile(r"['‘’ʼ`´]")


def strip_punctuation_variants(text: str) -> str:
    """Deletes apostrophe/quote-mark characters from `text` so possessive
    disease names normalize the same way whether the source spells them
    with a straight apostrophe, a curly/typographic one, or omits it
    entirely (a real, confirmed mismatch: ClinicalTrials.gov/openFDA/case
    input spell "Alzheimer's disease" one way, a case's free-text field
    might say "Alzheimers disease" another way, and Europe PMC/PubMed
    abstracts can use either straight `'` or curly `’` — all four must
    tokenize identically). Deliberately narrow: only apostrophe-family
    characters are touched, not general punctuation, so this can't merge
    two otherwise-distinct disease names together (e.g. "non-small cell
    lung cancer" still tokenizes on the hyphen exactly as before — hyphens
    aren't apostrophes)."""
    return _APOSTROPHE_RE.sub("", text)

# Generic trial-eligibility/study-metadata terms real ClinicalTrials.gov
# "conditions" sometimes use that are not actual diseases. Found by
# inspecting Step 3's live metformin pull (backend/scripts/ingest_clinicaltrials.py).
JUNK_CONDITION_TERMS = {
    "healthy",
    "healthy volunteers",
    "healthy subjects",
    "healthy male and female subjects",
    "health volunteer",
    "efficacy",
    "efficacy and safety",
    "safety",
    "quality of life",
    "pharmacokinetics",
    "bioequivalence",
    "comparative bioavailability",
    "drug interactions",
    "elderly",
    "overweight",
    "overweight subjects",
    "obese subjects",
    "disease-free survival",
    "overall survival",
    "exercise capacity",
    "gi side effect",
    "racial bias",
    "fixed dose combination tablets",
    "investigatorinitiate trial",
}

# A "condition" this long is almost never an actual disease name — it's
# study-description text that ended up in the Condition field (e.g. "the
# objectives of the study is to evaluate the efficacy and safety of..."). A
# real disease/indication name essentially never runs this long.
JUNK_CONDITION_MAX_WORDS = 8


def is_junk_condition(condition: str) -> bool:
    """True if `condition` is a generic trial-eligibility/metadata term or
    a description sentence rather than an actual disease/indication. Meant
    to be applied to *observed* conditions (e.g. from ClinicalTrials.gov)
    before they reach the comparison step — see scoring.py."""
    normalized = " ".join(condition.strip().lower().split())
    if not normalized:
        return True
    if normalized in JUNK_CONDITION_TERMS:
        return True
    if len(normalized.split()) > JUNK_CONDITION_MAX_WORDS:
        return True
    return False


# Bare, very generic disease-category words that are too vague to trust as
# a single-token match on their own (see is_too_generic_to_match).
OVERLY_GENERIC_SINGLE_TERMS = {
    "cancer",
    "disease",
    "syndrome",
    "tumor",
    "tumour",
    "disorder",
    "carcinoma",
    "neoplasm",
    "infection",
    "condition",
}


def is_too_generic_to_match(observed_tokens: set[str]) -> bool:
    """Guards the single-token false-positive risk: a bare, very generic
    observed term (e.g. just "cancer") is too unspecific to trust matching
    against arbitrary approved text, where that single word could appear
    anywhere (e.g. an unrelated boxed-warning sentence) without meaning the
    same disease is actually approved. Multi-token observed terms (e.g.
    "breast cancer") are unaffected — this only blocks the bare single-word
    case."""
    return len(observed_tokens) == 1 and next(iter(observed_tokens)) in OVERLY_GENERIC_SINGLE_TERMS


def disease_tokens(text: str, strip_qualifiers: bool = False) -> set[str]:
    """Lowercased word tokens, optionally with staging/qualifier words
    removed. Apostrophe characters are stripped before tokenizing (see
    strip_punctuation_variants) so "Alzheimer's disease" and "Alzheimers
    disease" produce the identical token set regardless of which form
    either side of a comparison happens to use."""
    words = _WORD_RE.findall(strip_punctuation_variants(text.lower()))
    if strip_qualifiers:
        words = [w for w in words if w not in STAGING_QUALIFIERS]
    return set(words)


def diseases_match(observed_disease: str, approved_disease: str) -> bool:
    """True if `observed_disease` (e.g. a trial condition like "Stage IV
    Pancreatic Cancer") should be treated as the same disease as
    `approved_disease` (e.g. a clean manual entry, or a whole openFDA
    indications-and-usage paragraph).

    Match rule: every meaningful token of the observed disease, after
    stripping staging/qualifier words, must appear somewhere in the
    approved text's tokens (staging words are NOT stripped from the
    approved side, and are almost never present there anyway). This is a
    one-directional, order-independent containment check:
      - "Stage IV Pancreatic Cancer" -> {"pancreatic", "cancer"} is a
        subset of {"pancreatic", "cancer"} from a clean approved entry.
        Match.
      - "pulmonary hypertension" -> {"pulmonary", "hypertension"} is a
        subset of the tokens in "...pulmonary arterial hypertension...".
        Match (this is intentional: PAH is a real subtype of pulmonary
        hypertension, and sildenafil genuinely is approved for it).
      - "pancreatic cancer" is NOT a subset of metformin's diabetes-focused
        approved text. No match — correctly still a signal.

    Guarded case: a bare, single-token, very generic observed disease (e.g.
    just "cancer") never matches, regardless of what the approved text
    contains — see `is_too_generic_to_match`. Multi-token generic terms
    ("breast cancer") are unaffected.
    """
    observed_tokens = disease_tokens(observed_disease, strip_qualifiers=True)
    if not observed_tokens:
        return False
    if is_too_generic_to_match(observed_tokens):
        return False
    approved_tokens = disease_tokens(approved_disease)
    return observed_tokens.issubset(approved_tokens)
