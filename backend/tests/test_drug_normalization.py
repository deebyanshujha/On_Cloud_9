"""Tests for drug-name normalization (Step 10) — the piece that lets
discovery-driven ingestion merge "Metformin Hydrochloride 500mg",
"metformin HCl", and "metformin" into one known-drug entity."""
from app.core.drug_normalization import normalize_drug_name


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
