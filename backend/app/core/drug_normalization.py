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
    "oral", "solution", "extended", "release", "er", "xr", "sr", "ir",
    "immediate", "delayed",
}

# Matches a dosage/strength token like "500mg", "10 mcg", "2.5g", "100units".
_STRENGTH_RE = re.compile(
    r"^\d+(\.\d+)?\s*(mg|mcg|g|ml|iu|units?)$", re.IGNORECASE
)

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")


def normalize_drug_name(raw: str) -> str:
    """Canonical form of a raw drug/intervention name string. Not a
    dictionary lookup — a deterministic text-cleanup heuristic (strip
    filler phrasing, strength tokens, and salt/form words), same spirit as
    `app/core/disease_matching.py`'s staging-qualifier stripping."""
    text = raw.strip()
    text = _LEADING_FILLER_RE.sub("", text)
    text = text.lower()
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
