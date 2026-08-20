"""Tests for the disease-name matching heuristic (Step 5), including the two
real cases that proved exact-string matching wrong in Steps 3 and 4, plus
the junk-condition filter and single-token-genericity guard added before
Step 6 to keep known data-quality gaps from being amplified by more
ingestion volume."""
from app.core.disease_matching import (
    diseases_match,
    disease_tokens,
    is_junk_condition,
    is_too_generic_to_match,
    strip_punctuation_variants,
)

# Real ClinicalTrials.gov condition text pulled in Step 3.
REAL_PANCREATIC_CANCER_CONDITION = "Stage IV Pancreatic Cancer"

# Real openFDA indications_and_usage text pulled in Step 4 (trimmed excerpt
# from the sildenafil/Revatio label).
REAL_SILDENAFIL_PAH_LABEL_TEXT = (
    "1 INDICATIONS & USAGE Sildenafil tablets are indicated for the "
    "treatment of pulmonary arterial hypertension (WHO Group I) in adults "
    "to improve exercise ability and delay clinical worsening."
)

# Real openFDA indications_and_usage text for metformin (no mention of
# cancer at all).
REAL_METFORMIN_LABEL_TEXT = (
    "1 INDICATIONS AND USAGE Metformin hydrochloride tablets are indicated "
    "as an adjunct to diet and exercise to improve glycemic control in "
    "adults with type 2 diabetes mellitus."
)


def test_staging_qualifier_is_stripped_and_matches():
    # Step 3's real case: fixture says "pancreatic cancer", real
    # ClinicalTrials.gov data says "Stage IV Pancreatic Cancer".
    assert diseases_match(REAL_PANCREATIC_CANCER_CONDITION, "pancreatic cancer")


def test_metformin_pancreatic_cancer_not_approved():
    # metformin/pancreatic cancer must still NOT match against metformin's
    # real approved-indications text — it's a genuine new signal, not an
    # already-approved use.
    assert not diseases_match("pancreatic cancer", REAL_METFORMIN_LABEL_TEXT)
    assert not diseases_match(
        REAL_PANCREATIC_CANCER_CONDITION, REAL_METFORMIN_LABEL_TEXT
    )


def test_sildenafil_pulmonary_hypertension_matches_pah_label_text():
    # Step 4's real case: fixture says "pulmonary hypertension", real
    # openFDA label text says "pulmonary arterial hypertension" — sildenafil
    # genuinely is approved for PAH, so this must now match (and therefore
    # get correctly discarded as "already approved", not flagged).
    assert diseases_match("pulmonary hypertension", REAL_SILDENAFIL_PAH_LABEL_TEXT)


def test_erectile_dysfunction_does_not_match_pah_text():
    # Sanity check the matcher isn't just returning True for anything
    # sildenafil-related.
    assert not diseases_match("erectile dysfunction", REAL_SILDENAFIL_PAH_LABEL_TEXT)


def test_various_staging_qualifiers_stripped():
    assert diseases_match("Metastatic Breast Cancer", "breast cancer")
    assert diseases_match("Recurrent Ovarian Cancer", "ovarian cancer")
    assert diseases_match("Advanced Renal Cell Carcinoma", "renal cell carcinoma")


def test_no_match_for_unrelated_disease():
    assert not diseases_match("multiple myeloma", "type 2 diabetes mellitus")


def test_empty_observed_disease_never_matches():
    assert not diseases_match("", "pancreatic cancer")
    assert not diseases_match("   ", "pancreatic cancer")


def test_match_is_not_required_in_reverse():
    # A short observed term matching inside a longer approved paragraph is
    # fine; the reverse (approved text being a subset of a short observed
    # term) is not required and not checked.
    assert diseases_match("type 2 diabetes mellitus", REAL_METFORMIN_LABEL_TEXT)
    assert not diseases_match(REAL_METFORMIN_LABEL_TEXT, "type 2 diabetes mellitus")


# --- apostrophe/punctuation-variant normalization (Case #17 regression) --
#
# Real bug: Case #17 (Alzheimer's Disease + Metformin) retrieved 60 real
# Europe PMC/PubMed papers about Alzheimer's disease, but 0 survived
# relevance filtering. Root cause: `_WORD_RE` (`[a-z0-9]+`) treats an
# apostrophe as a token boundary, so "Alzheimer's disease" tokenized to
# {"alzheimer", "s", "disease"} while the case's stored condition
# "alzheimers disease" (no apostrophe) tokenized to {"alzheimers",
# "disease"} — "alzheimers" (one token) never equals "alzheimer" + "s"
# (two tokens), so diseases_match returned False for genuinely matching
# text. Fixed by deleting apostrophe-family characters before tokenizing
# (strip_punctuation_variants), so every spelling collapses to the same
# token set.

REAL_ALZHEIMERS_ABSTRACT_TEXT = (
    "Alzheimer's disease is a progressive neurodegenerative disorder and "
    "the most common cause of dementia in older adults."
)


def test_alzheimers_disease_matches_apostrophe_form_no_apostrophe_form():
    assert diseases_match("alzheimers disease", REAL_ALZHEIMERS_ABSTRACT_TEXT)
    assert diseases_match("Alzheimers Disease", REAL_ALZHEIMERS_ABSTRACT_TEXT)


def test_alzheimers_disease_matches_straight_and_curly_apostrophes():
    straight = "Alzheimer's disease"
    curly = "Alzheimer’s disease"  # ’
    assert diseases_match(straight, curly)
    assert diseases_match(curly, straight)
    assert diseases_match("alzheimers disease", curly)
    assert diseases_match("alzheimers disease", straight)


def test_apostrophe_normalization_is_generic_not_hardcoded_to_alzheimers():
    # Same class of possessive disease name, different disease entirely —
    # the fix must not be a special case for "Alzheimer's" specifically.
    assert diseases_match("parkinsons disease", "Parkinson's disease is a movement disorder.")
    assert diseases_match("crohns disease", "Crohn’s disease causes intestinal inflammation.")
    assert diseases_match("graves disease", "Graves' disease is an autoimmune thyroid condition.")


def test_apostrophe_normalization_does_not_create_false_positive_matches():
    # Stripping apostrophes must not make genuinely different diseases
    # match each other.
    assert not diseases_match("alzheimers disease", "Parkinson's disease is a movement disorder.")
    assert not diseases_match("parkinsons disease", REAL_ALZHEIMERS_ABSTRACT_TEXT)


def test_apostrophe_normalization_does_not_merge_unrelated_hyphenated_terms():
    # Only apostrophe-family characters are stripped — hyphens and other
    # punctuation still tokenize exactly as before, so this fix can't
    # accidentally widen matching beyond possessive-name variants.
    assert not diseases_match(
        "non-small cell lung cancer", "small cell lung cancer is a distinct, more aggressive subtype."
    )


def test_strip_punctuation_variants_only_touches_apostrophe_characters():
    assert strip_punctuation_variants("Alzheimer's disease") == "Alzheimers disease"
    assert strip_punctuation_variants("Alzheimer’s disease") == "Alzheimers disease"
    assert strip_punctuation_variants("non-small cell lung cancer") == "non-small cell lung cancer"
    assert strip_punctuation_variants("Stage IV Pancreatic Cancer") == "Stage IV Pancreatic Cancer"


def test_existing_staging_and_pah_cases_still_pass_after_apostrophe_fix():
    # Preserve pre-existing behavior: this fix must not regress the two
    # real cases the matcher was originally built for.
    assert diseases_match(REAL_PANCREATIC_CANCER_CONDITION, "pancreatic cancer")
    assert diseases_match("pulmonary hypertension", REAL_SILDENAFIL_PAH_LABEL_TEXT)
    assert not diseases_match("erectile dysfunction", REAL_SILDENAFIL_PAH_LABEL_TEXT)
    assert not diseases_match("pancreatic cancer", REAL_METFORMIN_LABEL_TEXT)


# --- is_junk_condition -------------------------------------------------
# Real junk "conditions" pulled straight from Step 3's live metformin run
# (backend/scripts/ingest_clinicaltrials.py) — generic trial-eligibility
# terms and study-description text, not actual diseases.
REAL_JUNK_CONDITIONS = [
    "healthy",
    "healthy volunteers",
    "healthy male and female subjects",
    "efficacy",
    "overweight",
    "overweight subjects",
    "safety",
    "quality of life",
    "pharmacokinetics",
    "bioequivalence",
    "drug interactions",
    "elderly",
    "the objectives of the study is to evaluate the efficacy and safety of acarmet (metformin hcl 500 mg",
    "metformin and insulin glargine combined with chiglitazar sodium tablets 48mg/ day group",
]

REAL_DISEASE_CONDITIONS = [
    "pancreatic cancer",
    "Stage IV Pancreatic Cancer",
    "type 2 diabetes mellitus",
    "polycystic ovary syndrome",
    "obesity",
    "pulmonary hypertension",
]


def test_real_junk_conditions_are_filtered():
    for junk in REAL_JUNK_CONDITIONS:
        assert is_junk_condition(junk), f"expected {junk!r} to be flagged as junk"


def test_real_disease_conditions_are_not_filtered():
    for disease in REAL_DISEASE_CONDITIONS:
        assert not is_junk_condition(disease), f"did not expect {disease!r} to be flagged as junk"


def test_junk_condition_matching_is_case_and_whitespace_insensitive():
    assert is_junk_condition("  Healthy  Volunteers  ")
    assert is_junk_condition("HEALTHY")


def test_empty_condition_is_junk():
    assert is_junk_condition("")
    assert is_junk_condition("   ")


# --- is_too_generic_to_match --------------------------------------------


def test_bare_generic_single_term_is_too_generic():
    assert is_too_generic_to_match(disease_tokens("cancer"))
    assert is_too_generic_to_match(disease_tokens("syndrome"))
    assert is_too_generic_to_match(disease_tokens("disease"))


def test_multi_token_term_with_generic_word_is_not_blocked():
    assert not is_too_generic_to_match(disease_tokens("breast cancer"))
    assert not is_too_generic_to_match(disease_tokens("pancreatic cancer"))


def test_specific_single_token_disease_is_not_blocked():
    assert not is_too_generic_to_match(disease_tokens("obesity"))
    assert not is_too_generic_to_match(disease_tokens("dengue"))


def test_bare_generic_term_does_not_spuriously_match_unrelated_approved_text():
    # The false-positive risk flagged after Step 5: a bare "cancer" must
    # NOT match just because the word appears somewhere in unrelated
    # approved text (e.g. a boxed warning mentioning cancer risk).
    unrelated_text_mentioning_cancer_in_passing = (
        "Indicated for the treatment of erectile dysfunction. Postmarketing "
        "reports have not established a causal link to cancer."
    )
    assert not diseases_match("cancer", unrelated_text_mentioning_cancer_in_passing)
    # But a real, specific match still works normally.
    assert diseases_match("breast cancer", "indicated for the treatment of breast cancer")
