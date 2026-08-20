"""Drug-name normalization (Step 10).

Discovery-driven ingestion pulls drug names straight out of free-text
fields (ClinicalTrials.gov intervention names, NER-extracted chemical
mentions) instead of a hand-typed list, so the same real-world drug shows
up under many different surface forms:

  - brand vs. generic ("Glucophage" vs. "metformin")
  - salt/dosage-form suffixes ("Metformin Hydrochloride 500mg",
    "Metformin HCl ER Tablet")
  - filler phrasing that ClinicalTrials.gov intervention names carry
    ("Dose reduction of lezertinib", "Supplementation of magnesium
    lactate")
  - plain case/whitespace differences

`normalize_drug_name` collapses all of these to one canonical string so the
known-drugs cache (app/ingestion/store.py) and the comparison engine
(app/core/scoring.py, via Document.normalized_drug()) merge them into a
single entity instead of treating each surface form as a different drug.
This extends the existing lowercase/strip normalization already used by
`Document.normalized_drug()` / `ApprovedIndication.normalized_drug()`
rather than building a second, parallel system.
"""
from __future__ import annotations

import re
from functools import lru_cache

import httpx

RXNORM_RXCUI_URL = "https://rxnav.nlm.nih.gov/REST/rxcui.json"

# Leading filler phrases ClinicalTrials.gov intervention names sometimes
# carry that describe the study action, not the drug itself.
_LEADING_FILLER_RE = re.compile(
    r"^(dose (reduction|escalation|increase) of|supplementation of|"
    r"administration of|treatment with|combination of)\s+",
    re.IGNORECASE,
)

# Salt/ester/form and route/release-profile words that vary between labels
# of the same active ingredient (e.g. "metformin hydrochloride" and
# "metformin" are the same drug for repurposing-signal purposes).
_SALT_AND_FORM_WORDS = {
    "hydrochloride", "hcl", "sodium", "potassium", "sulfate", "sulphate",
    "citcitrate", "citrate", "phosphate", "acetate", "besylate", "maleate",
    "mesylate", "tartrate", "succinate", "hemihydrate", "monohydrate",
    "tablet", "tablets", "capsule", "capsules", "injection", "injectable",
    "oral", "pill", "pills", "solution", "extended", "release", "er", "xr", "sr", "ir",
    "immediate", "delayed",
}

# Matches a dosage/strength token like "500mg", "10 mcg", "2.5g", "100units".
_STRENGTH_RE = re.compile(
    r"^\d+(\.\d+)?\s*(mg|mcg|g|ml|iu|units?)$", re.IGNORECASE
)

# Same strength pattern, but matched inline against the whole string before
# tokenizing — CT.gov intervention names commonly space the number from the
# unit ("Ertugliflozin 5 mg", "Ertugliflozin 15 mg"), which _STRENGTH_RE's
# single-token match can't catch (it'd see "5" and "mg" as two separate,
# individually-innocuous tokens) and which would otherwise leave dose
# variants of the same drug as distinct canonical names.
_STRENGTH_INLINE_RE = re.compile(
    r"\b\d+(\.\d+)?\s*(mg|mcg|g|ml|iu|units?)\b", re.IGNORECASE
)

# Trial-structure suffixes CT.gov intervention names sometimes carry
# ("Pemefolacianib Cohort 1 In Part A") — describes the study arm, not the
# drug, same spirit as _LEADING_FILLER_RE but on the tail end. `(?:^|\s)`
# (not `\s*`) so "cohort"/"arm"/"group"/"part" must be a standalone word —
# matching either at the very start of the string (a BARE label like
# "Cohort 1") or right after whitespace — never mid-word (so a drug name
# that coincidentally ends in those letters, e.g. hypothetically "Xelarm",
# is never truncated).
_TRAILING_FILLER_RE = re.compile(
    r"(?:^|\s)((cohort|arm|group)\s+[a-z0-9]+(\s+in\s+part\s+[a-z0-9]+)?|part\s+[a-z0-9]+)\s*$",
    re.IGNORECASE,
)

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")

# Exact-match non-drug intervention names (case/punctuation-insensitive).
# ClinicalTrials.gov sponsors routinely tag these as intervention type
# "DRUG" even though they're a comparator/procedure/behavioral arm, not a
# medication — a real quirk of their taxonomy, not a bug in the
# type == "DRUG" filter in app/ingestion/clinicaltrials.py.
_JUNK_EXACT_NAMES = {
    "placebo", "placebo comparator", "placebo oral tablet", "matching placebo",
    "sham", "sham procedure", "sham surgery",
    "standard of care", "usual care", "best supportive care",
    "observation", "no intervention", "no treatment", "watchful waiting",
    "surgery", "procedure", "device", "behavioral", "behavioral intervention",
    "dietary supplement", "educational", "diet", "guideline", "questionnaire",
    "exercise", "physical therapy", "counseling", "usual treatment",
}

# Tokens that never appear inside a real drug/ingredient name — unlike the
# exact-name/length checks above, these are safe to match anywhere in the
# string, since "Placebo (subcutaneous)" or "Matching Placebo Injection" are
# exactly as non-drug as bare "Placebo". Checked as whole words, not
# substrings, so this can't accidentally reject a real drug name that merely
# contains these letters.
_JUNK_TOKENS = {"placebo", "sham"}


# A "drug" name this long is almost never a real medication — it's
# description/protocol text that leaked into the intervention field (e.g.
# "Rapid ESC-Guideline Based Secondary Prevention Following Myocardial
# Infaction"). Same length-heuristic spirit as
# app/core/disease_matching.py's is_junk_condition.
_JUNK_MAX_WORDS = 8


def _basic_clean(raw: str) -> str:
    text = raw.strip().lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def is_junk_drug_name(raw: str) -> bool:
    """True if `raw` is not a real medication entity: a placebo/comparator
    arm, a procedure/device/behavioral/dietary intervention mistagged as
    type DRUG, a bare cohort/arm/part study-structure label with nothing
    substantive left after stripping, or protocol/description text that
    leaked into the intervention name field. Checked before normalizing so
    junk never even reaches the salt/form/filler cleanup."""
    if not raw or not raw.strip():
        return True

    cleaned = _basic_clean(raw)
    if cleaned in _JUNK_EXACT_NAMES:
        return True
    if _JUNK_TOKENS & set(cleaned.split()):
        return True

    stripped = _TRAILING_FILLER_RE.sub("", raw.strip())
    remainder = _basic_clean(stripped)
    if not remainder or remainder in _JUNK_EXACT_NAMES:
        return True

    if len(remainder.split()) > _JUNK_MAX_WORDS:
        return True

    return False


# Real drug-CLASS terms that RxNorm won't resolve as a single ingredient
# concept (RxNorm models ingredients, not therapeutic classes) — kept
# deliberately short and explicit rather than guessed at. A name in this
# set is a legitimate medication-class entity, not junk, even though
# resolve_rxnorm_id() will return None for it.
DRUG_CLASS_ALLOWLIST = {
    "5-asa", "5 asa", "5-aminosalicylic acid",
    "glp-1 receptor agonists", "glp 1 receptor agonists",
    "sglt2 inhibitors", "sglt 2 inhibitors",
    "ace inhibitors", "beta blockers", "statins",
}


def is_valid_medication_entity(canonical_name: str) -> bool:
    """Authoritative validation gate: true only if `canonical_name` resolves
    to a real RxNorm concept, or is one of the small curated drug-class
    terms above. This is stricter than is_junk_drug_name (which only
    rejects obvious non-drug text) — it requires positive confirmation from
    an authoritative terminology source. Used for retroactive cleanup
    (scripts/clean_junk_medications.py) and the autocomplete/entity
    endpoints (app/core/terminology.py), NOT live discovery ingestion:
    network-gating every discovered drug against RxNav in real time, once
    per study per run, would be slow and flaky for no benefit over the
    is_junk_drug_name reject-list already applied at ingestion time."""
    if not canonical_name:
        return False
    if canonical_name in DRUG_CLASS_ALLOWLIST:
        return True
    return resolve_rxnorm_id(canonical_name) is not None


def normalize_drug_name(raw: str) -> str:
    """Canonical form of a raw drug/intervention name string. Not a
    dictionary lookup — a deterministic text-cleanup heuristic (strip
    filler phrasing, strength tokens, and salt/form words), same spirit as
    `app/core/disease_matching.py`'s staging-qualifier stripping."""
    text = raw.strip()
    text = _LEADING_FILLER_RE.sub("", text)
    text = _TRAILING_FILLER_RE.sub("", text)
    text = text.lower()
    text = _STRENGTH_INLINE_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)

    tokens = [t for t in _WHITESPACE_RE.split(text) if t]
    kept = [
        t for t in tokens
        if t not in _SALT_AND_FORM_WORDS and not _STRENGTH_RE.match(t)
    ]
    if not kept:
        # Everything looked like a salt/strength/form word (unlikely, but
        # don't collapse to an empty string) — fall back to the raw tokens.
        kept = tokens

    return " ".join(kept)


@lru_cache(maxsize=512)
def resolve_rxnorm_id(canonical_name: str) -> str | None:
    """Best-effort RxNorm CUI lookup via RxNav's free, no-login REST API.
    Returns None (never raises) if the name doesn't resolve or the service
    is unreachable — RxNorm enrichment is a nice-to-have on the known-drugs
    cache, not a requirement for ingestion to work."""
    if not canonical_name:
        return None
    try:
        response = httpx.get(
            RXNORM_RXCUI_URL, params={"name": canonical_name}, timeout=10.0
        )
        response.raise_for_status()
        ids = response.json().get("idGroup", {}).get("rxnormId") or []
        return ids[0] if ids else None
    except (httpx.HTTPError, ValueError, KeyError):
        return None
