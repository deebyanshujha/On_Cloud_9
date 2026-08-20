"""Tests for drug-name normalization (Step 10) — the piece that lets
discovery-driven ingestion merge "Metformin Hydrochloride 500mg",
"metformin HCl", and "metformin" into one known-drug entity."""
from app.core.drug_normalization import (
    DRUG_CLASS_ALLOWLIST,
    is_junk_drug_name,
    is_valid_medication_entity,
    normalize_drug_name,
)


def test_normalize_lowercases_and_strips_whitespace():
    assert normalize_drug_name("  Metformin  ") == "metformin"


def test_normalize_strips_salt_and_dosage_form():
    assert normalize_drug_name("Metformin Hydrochloride 500mg") == "metformin"
    assert normalize_drug_name("Metformin HCl ER Tablet") == "metformin"


def test_normalize_strips_ctgov_filler_phrasing():
    assert normalize_drug_name("Dose reduction of lezertinib") == "lezertinib"
    assert normalize_drug_name("Supplementation of magnesium lactate") == "magnesium lactate"


def test_normalize_different_surface_forms_converge():
    assert normalize_drug_name("Metformin") == normalize_drug_name("metformin 500mg tablet")
    assert normalize_drug_name("METFORMIN") == normalize_drug_name("Metformin Hydrochloride")


def test_normalize_distinct_drugs_stay_distinct():
    assert normalize_drug_name("metformin") != normalize_drug_name("sildenafil")


# --- Junk-drug-name rejection (TheraLens redesign Phase A, 2026-08-20) -----
# Real examples pulled from the live dataset before this filter existed —
# see PROGRESS.md's redesign audit.


def test_placebo_is_rejected():
    assert is_junk_drug_name("Placebo") is True
    assert is_junk_drug_name("Placebo Comparator") is True
    assert is_junk_drug_name("placebo oral tablet") is True


def test_procedures_and_non_drug_interventions_are_rejected():
    assert is_junk_drug_name("Surgery") is True
    assert is_junk_drug_name("Behavioral Intervention") is True
    assert is_junk_drug_name("Standard of Care") is True
    assert is_junk_drug_name("Best Supportive Care") is True


def test_bare_cohort_or_part_labels_are_rejected():
    assert is_junk_drug_name("Cohort 1") is True
    assert is_junk_drug_name("Part A") is True


def test_real_drug_with_cohort_suffix_is_stripped_not_rejected():
    assert is_junk_drug_name("Pemefolacianib Cohort 1 In Part A") is False
    assert normalize_drug_name("Pemefolacianib Cohort 1 In Part A") == "pemefolacianib"


def test_long_protocol_sentence_is_rejected():
    assert is_junk_drug_name(
        "Rapid ESC-Guideline Based Secondary Prevention Following Myocardial Infaction"
    ) is True


def test_real_drug_names_are_not_rejected():
    for name in ["Toradol", "Oxycodone", "metformin", "5-ASA", "Lezertinib"]:
        assert is_junk_drug_name(name) is False


def test_empty_or_blank_is_rejected():
    assert is_junk_drug_name("") is True
    assert is_junk_drug_name("   ") is True


# --- RxNorm-gated medication validity ---------------------------------------


def test_drug_class_allowlist_entries_are_valid_without_network():
    for name in DRUG_CLASS_ALLOWLIST:
        assert is_valid_medication_entity(name) is True


def test_empty_name_is_never_valid():
    assert is_valid_medication_entity("") is False


def test_valid_medication_entity_uses_rxnorm_resolution(monkeypatch):
    import app.core.drug_normalization as dn

    monkeypatch.setattr(dn, "resolve_rxnorm_id", lambda name: "6809" if name == "metformin" else None)
    assert is_valid_medication_entity("metformin") is True
    assert is_valid_medication_entity("totally not a drug") is False
