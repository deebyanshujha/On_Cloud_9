# Progress Log — Real-Time Biotech Arbitrage Engine

_Last updated: 2026-08-19 — after TheraLens Phase 3 (new-evidence detection for saved cases, detail at the bottom of this file)_

## What is this project, in plain terms?

Drugs sometimes turn out to work for diseases they were never originally
approved for. Doctors and researchers notice this early, often years before
a drug officially gets approved for the new use — you can see it happening
in the wild because researchers start running clinical trials or publishing
papers testing "old drug" on "new disease" long before the FDA signs off.

This project watches for that pattern automatically. It reads public
databases of clinical trials and research papers, figures out which
drug-disease pairs are being studied, checks each pair against the FDA's
official list of what that drug is *already* approved for, and flags the
ones that are new. Those flags are the "repurposing signals" — early,
public, free hints that a drug might be quietly proving itself in a new
disease area before that becomes common knowledge.

Nothing here uses ChatGPT/Claude/any paid AI API. All the "understanding
free text" work is done with open-source biomedical NLP models
(scispaCy/BioBERT) that run locally, and all the data sources are free,
public, no-login APIs (ClinicalTrials.gov, bioRxiv/medRxiv, openFDA).

**Note on the architecture diagram:** the uploaded diagram (`biotech_arbitrage_diagram.html`)
shows "Claude API" as the extraction method for unstructured text. That was
an earlier draft. The actual build uses scispaCy/BioBERT NER instead — no
LLM APIs anywhere — per an explicit project constraint. Everything else in
the diagram (data sources, comparison logic, scoring, storage, serving) is
being followed as designed.

## Why each major piece exists

| Piece | Why it exists |
|---|---|
| **Ingestion scripts** (ClinicalTrials.gov, bioRxiv) | Turn each source's own weird format into one common shape: `{drug, disease, source, date, url}`. Nothing downstream needs to know where the data came from. |
| **openFDA ground truth lookup** | Without knowing what a drug is *already* approved for, you can't tell a "new" pairing from an "old, boring" one. This is the yardstick everything gets measured against. |
| **Comparison engine** | The actual "is this new?" decision. For every observed drug-disease pair, checks it against the ground truth and throws away anything already approved. |
| **Scoring** | Not every new pairing is equally interesting. A Phase 3 trial mentioned twice this month is a stronger signal than one old Phase 1 trial. Scoring ranks signals so the best ones float to the top. |
| **NER (scispaCy/BioBERT)** | ClinicalTrials.gov gives structured fields (easy), but research paper abstracts are just paragraphs of text. NER pulls drug and disease names out of that free text without needing a paid LLM. |
| **Database (Postgres/SQLite)** | Stores every document and every signal so the dashboard doesn't have to re-fetch and re-compute everything on every page load. |
| **FastAPI backend** | Exposes the signals as an API (`/signals`, `/signals/{drug}`, `/search`) so any frontend (or `curl`) can read them. |
| **React dashboard** | Human-friendly way to browse the ranked signal feed and click through to the original trial or paper. |
| **Scheduler** *(deferred — see Step 7 status below)* | Keeps the data fresh — re-polls the sources every so often instead of requiring someone to manually re-run scripts. |

## Build order and current status

- [x] **Step 1 — Project structure.** `backend/`, `frontend/`, `shared/` are
  set up. `shared/schema.md` documents the three shapes (`Document`,
  `ApprovedIndication`, `Signal`) that every part of the system agrees on.
- [x] **Step 2 — Core comparison/scoring logic, proven with hardcoded data.**
  This is done and **tested**, using zero real API calls. Details below.
- [x] **Step 3 — ClinicalTrials.gov ingestion.** Done and verified with
  real, live data (not mocked). Details below.
- [x] **Step 4 — openFDA Drug Label lookup (ground truth).** Done and
  verified with real, live data (not mocked). Details below.
- [x] **Step 5 — Fix disease-name matching, then wire real trial data +
  openFDA into the comparison engine.** Done and verified end to end with
  real, live data. Details below.
- [x] **Step 6 — bioRxiv/medRxiv ingestion + scispaCy NER.** Done and
  verified with real, live data. Details below.
- [ ] **Step 7 — Scheduler for periodic re-polling.** Deliberately
  **deferred** (not skipped) in favor of Step 8 — a working, demo-ready
  dashboard matters more right now than an unattended background poller.
  All the pieces it would orchestrate (Steps 3/4/6 ingestion + Step 5
  comparison) already exist and are reusable as-is whenever this gets
  picked back up.
- [x] **Step 8 — FastAPI backend + React dashboard.** Done and verified
  end to end with real, live data (677 documents, 351 signals) — API
  running, frontend rendering, both checked in a real browser. Details
  below.
- [x] **Step 9 — Validation against known cases using live data.** Folded
  into Step 10: the two original watch pairs (metformin/pancreatic cancer,
  sildenafil/pulmonary hypertension) are now a permanent regression check
  inside `scripts/run_pipeline.py`, re-verified on every discovery run —
  see Step 10 detail below.
- [x] **Step 10 — Remove the 2-drug hardcoded ceiling; dynamic,
  discovery-driven ingestion.** Done and verified with real, live data.
  Details below.

## What's actually built right now (Step 2 detail)

**Files:**
- `backend/app/schemas/document.py` — the three shared data shapes
  (`Document`, `ApprovedIndication`, `Signal`), as Pydantic models.
- `backend/app/core/scoring.py` — the comparison + scoring engine. Pure
  Python, no database, no network calls, no web framework. Takes a list of
  `Document` and a list of `ApprovedIndication`, returns ranked `Signal`s.
- `backend/data/known_cases.json` — hand-written fixture with the three
  examples from the brief (metformin→pancreatic cancer,
  sildenafil→pulmonary hypertension, thalidomide→multiple myeloma), plus a
  "control" pair (metformin→type 2 diabetes) that should NOT be flagged
  because it's already approved.
- `backend/tests/test_scoring.py` — 5 automated tests, all passing:
  - rediscovers all three known repurposing signals
  - correctly ignores the already-approved control pair
  - signals come out sorted highest-score-first
  - independent mentions get correctly counted/combined
  - every score lands in the valid 0–1 range
- `backend/demo_scoring.py` — run `py demo_scoring.py` from `backend/` for
  a plain human-readable printout of the same result.

**How scoring works (current version, hackathon-tuned, not a calibrated
model):** each flagged pair gets points for (a) how strong its source is
(a real trial counts more than a preprint), (b) how far along the trial
phase is, (c) how recent the evidence is, and (d) how many independent
documents mention the same pair. Points are added up and capped at 1.0.

**Known limitation (by design, for now):** matching a studied disease
against the approved-indications list is an *exact* string match after
lowercasing/trimming. A real system would use a medical ontology (MeSH,
RxNorm) so "type 2 diabetes" and "diabetes mellitus, type 2" are recognized
as the same thing. This is fine for the hardcoded fixture; it will matter
once real openFDA/ClinicalTrials.gov text flows through in Steps 3-5 —
flagged as a thing to revisit then, not before.

**Ground truth note for the fixture:** the three approved indications in
`known_cases.json` are each drug's *original* approval (metformin →
diabetes, sildenafil → erectile dysfunction, thalidomide → leprosy-related
ENL) rather than their current, already-repurposed approval. This is
intentional — it's what lets the engine "discover" pancreatic cancer,
pulmonary hypertension, and multiple myeloma as new, exactly like it would
have looked in real life before those repurposings were approved.

## What's actually built right now (Step 3 detail)

**What it does:** pulls real studies from ClinicalTrials.gov (the free,
no-login v2 API) for a given drug name, and turns each one into one or more
`{drug, disease, source, date, url}` records — one record per condition a
study lists, since a single trial can study a drug against several
diseases at once. Records get saved into a local SQLite database
(`backend/data/arbitrage.db`), skipping anything already stored so the
script can be re-run safely without creating duplicates.

**Files:**
- `backend/app/ingestion/clinicaltrials.py` — talks to the
  ClinicalTrials.gov API, paginates through results, and converts each raw
  study into `Document` objects. Also normalizes trial phase codes
  (`"PHASE2"` → `"phase 2"`) and partial dates (`"2006-09"` → Sept 1, 2006)
  into the shapes the rest of the system expects.
- `backend/app/models/db.py` + `backend/app/models/document.py` — SQLite
  setup and the `documents` table (SQLAlchemy). Chose SQLite over Postgres
  for local dev per the brief — it's a single file, no server to run, easy
  to delete and start over. Swapping to Postgres later is a one-line
  `DATABASE_URL` change; nothing else depends on which database it is.
- `backend/app/ingestion/store.py` — saves `Document`s into the database,
  skipping exact duplicates (matched on source + source ID + drug +
  disease) so re-running ingestion is safe.
- `backend/scripts/ingest_clinicaltrials.py` — the runnable sanity-check
  script requested for this step. Run with `py scripts/ingest_clinicaltrials.py`
  from `backend/`.
- `backend/tests/test_clinicaltrials.py`, `backend/tests/test_store.py` —
  11 new automated tests covering parsing (phase normalization, partial
  dates, multi-condition studies, malformed studies) and storage
  (insert, dedupe-on-rerun, case normalization). All passing — 19/19 tests
  pass project-wide.

**Explicitly NOT done in this step (by instruction):** none of this is
wired into the comparison/scoring engine yet — that's Step 5. Right now
real trial data flows only as far as the database.

**Live sanity check results (2026-08-19), pulling real data for metformin
and sildenafil, capped at 200 studies per drug for a quick check:**

- metformin: 290 drug-disease documents parsed and stored (3,105 metformin
  trials exist in total on ClinicalTrials.gov — we only pulled the first
  200 studies as a sample, not the full set).
- sildenafil: 267 drug-disease documents parsed and stored.
- Re-running the script a second time correctly stored 0 new / all
  duplicates skipped — confirms de-duplication works.
- **sildenafil → "pulmonary hypertension": FOUND** in the real data,
  exactly matching the Step 2 known case.
- **metformin → "pancreatic cancer": NOT found** in the real data — but
  the real trials *do* exist, they're just titled things like *"Stage IV
  Pancreatic Cancer"* and *"Stage IA Pancreatic Cancer"* rather than the
  plain string `"pancreatic cancer"`. This is the exact limitation flagged
  in Step 2 (exact-string matching instead of ontology/fuzzy matching) —
  now confirmed against real data instead of just a hypothetical. It
  doesn't block Step 3 (storage is correct either way), but it means Step 5
  (wiring real data into the comparison engine) will need at least a
  light-touch normalization step — e.g. matching on "does the approved
  disease name appear as a substring of the observed disease name" — or
  the metformin/pancreatic-cancer known case won't get rediscovered from
  live data. Flagged as the first thing to address in Step 5.

## What's actually built right now (Step 4 detail)

**What it does:** pulls real drug label data from openFDA's Drug Label API
(the free, no-login endpoint) for a given generic drug name, and turns each
matching label into one `ApprovedIndication` record — the ground truth
Step 5's comparison engine will check observed drug-disease pairs against.
Records get saved into the same local SQLite database as Step 3
(`backend/data/arbitrage.db`, new `approved_indications` table), skipping
anything already stored so the script can be re-run safely.

**Important shape note:** openFDA's `indications_and_usage` field is a
free-text paragraph (e.g. *"...indicated as an adjunct to diet and exercise
to improve glycemic control in adults with type 2 diabetes mellitus..."*),
not a clean list of disease names — unlike ClinicalTrials.gov's structured
`Condition` field. Per this step's instructions, no extraction/splitting
was attempted; the whole paragraph is stored as-is in `ApprovedIndication.disease`,
one row per label. `shared/schema.md`'s `ApprovedIndication` shape also
gained a `source_id` field (the openFDA label `id`) so this step could dedupe
the same way Step 3 dedupes `Document`s — that's the only schema change made.

**Files:**
- `backend/app/ingestion/openfda.py` — talks to the openFDA Drug Label API
  and converts each raw label into an `ApprovedIndication` object.
- `backend/app/models/approved_indication.py` — the `approved_indications`
  SQLAlchemy table, mirroring `document.py`'s pattern.
- `backend/app/ingestion/store.py` — gained
  `upsert_approved_indications`/`load_all_approved_indications`, same
  dedupe strategy as the `Document` functions (source + source_id + drug +
  disease).
- `backend/scripts/ingest_openfda.py` — the runnable sanity-check script
  requested for this step. Run with `py scripts/ingest_openfda.py` from
  `backend/`.
- `backend/tests/test_openfda.py`, additions to `backend/tests/test_store.py`
  — 8 new automated tests covering parsing (basic fields, multi-paragraph
  joining, malformed labels) and storage (insert, dedupe-on-rerun, case
  normalization). All passing — 27/27 tests pass project-wide.

**Explicitly NOT done in this step (by instruction):** disease-name
matching/normalization was not touched — that's Step 5's decision. openFDA
ingestion only stores raw label text; nothing compares it against
ClinicalTrials.gov data yet.

**Live sanity check results (2026-08-19), pulling real data for metformin
and sildenafil, capped at 10 labels per drug:**

- metformin: 10 labels parsed and stored, all describing type 2 diabetes
  mellitus. **"pancreatic cancer" NOT found** in any approved-indications
  text — confirms this really is a candidate new pairing, not an
  already-approved one.
- sildenafil: 10 labels parsed and stored. Most describe erectile
  dysfunction, but several (the Revatio-brand labels) describe **"pulmonary
  arterial hypertension"** — sildenafil genuinely is FDA-approved for PAH,
  a subtype of pulmonary hypertension. The sanity check's literal substring
  search for `"pulmonary hypertension"` still reported "not found," because
  that exact phrase never appears — the label text says "pulmonary
  **arterial** hypertension" instead, so the substring is not contiguous.
  **This is a false negative and a real example of the exact disease-matching
  gap Step 5 needs to solve** — a naive matcher would wrongly treat
  sildenafil→pulmonary hypertension as a brand-new signal when sildenafil
  is already partially approved for it. Flagged as a concrete case to test
  against once Step 5's matching logic is built (plain substring matching
  as used in the Step 3 sanity check is not sufficient by itself).
- Re-running the script a second time correctly stored 0 new / all
  duplicates skipped — confirms de-duplication works.

## What's actually built right now (Step 5 detail)

**What it does:** replaces exact-string disease matching with a
staging/qualifier-aware token match, then runs the real documents/approved
indications already sitting in the database (from Steps 3 and 4) through
the comparison/scoring engine end to end.

**The matching rule (`app/core/disease_matching.py`, `diseases_match`):**
lowercase and tokenize both sides; strip a fixed list of staging/qualifier
words (`stage`, roman numerals `i`-`vi`, `metastatic`, `recurrent`,
`advanced`, `relapsed`, `refractory`, `unresectable`, `localized`, `grade`)
from the **observed** disease only; then check whether every remaining
observed token is present in the **approved** text's token set (a
one-directional subset check, not exact match or equality). This single
rule fixes both real cases from Steps 3/4:
- `"Stage IV Pancreatic Cancer"` → tokens `{pancreatic, cancer}` after
  stripping `stage`/`iv` → subset of `{pancreatic, cancer}` from a clean
  approved entry → **matches**.
- `"pulmonary hypertension"` → tokens `{pulmonary, hypertension}` → subset
  of the tokens in openFDA's `"...pulmonary arterial hypertension..."`
  paragraph (i.e. `{..., pulmonary, arterial, hypertension, ...}`) →
  **matches** — correctly, since sildenafil (Revatio) really is approved
  for PAH. No special-casing of "arterial" was needed; token-subset
  containment handles it because the *approved* side is allowed to have
  extra words the *observed* side doesn't.

**`app/core/scoring.py` changes:** `is_already_approved` and
`build_approved_index` now use `diseases_match` instead of exact
normalized-string set membership. `build_approved_index` changed from
`dict[str, set[str]]` (deduped clean phrases) to `dict[str, list[str]]`
(raw disease texts, since openFDA entries are full paragraphs that can't be
deduped as a set of short phrases).

**Files:**
- `backend/app/core/disease_matching.py` — the matching function, with the
  reasoning and a documented sharp edge in its docstring (see "Judgment
  calls" below).
- `backend/app/core/scoring.py` — wired to use it.
- `backend/tests/test_disease_matching.py` — 8 new tests, including the two
  real cases verbatim (real ClinicalTrials.gov condition text, real
  openFDA label excerpts) plus other staging-qualifier examples (metastatic
  breast cancer, recurrent ovarian cancer, advanced renal cell carcinoma)
  and negative controls (unrelated diseases, erectile dysfunction vs. PAH
  text, empty string). All passing — 35/35 tests pass project-wide.
- `backend/scripts/run_pipeline.py` — the end-to-end wiring script
  requested for this step. Loads the real documents/approved indications
  already stored by Steps 3/4's ingestion scripts, runs
  `run_comparison`, prints the top signals, and explicitly checks the two
  watch pairs. Run with `py scripts/run_pipeline.py` from `backend/`
  (requires having already run `ingest_clinicaltrials.py` and
  `ingest_openfda.py` at least once).

**Live end-to-end results (2026-08-19), using the real data already in
`arbitrage.db` from Steps 3/4 (557 documents, 20 approved indications):**

- Comparison produced 301 signals total.
- **metformin / pancreatic cancer: FLAGGED as signal** — matched via
  `"stage iv pancreatic cancer"`, score 0.720. This was the Step 3 false
  negative; now fixed.
- **sildenafil / pulmonary hypertension: NOT flagged** — correctly
  discarded as already approved (matches openFDA's PAH label text). This
  was the Step 4 false-positive risk; now fixed.

## Data-quality fixes pulled forward from "known issues" (before Step 6)

Two gaps flagged after Step 5 were fixed now rather than left for later,
specifically because Step 6 adds a third ingestion source (bioRxiv/medRxiv)
on top of an already-unfiltered base — better to filter/guard once than let
more volume amplify the same junk.

1. **Junk trial-condition filter** (`is_junk_condition` in
   `app/core/disease_matching.py`). Step 5's live pipeline run showed real
   ClinicalTrials.gov "conditions" that aren't diseases at all — generic
   trial-eligibility/study-metadata terms (`healthy`, `efficacy`, `safety`,
   `overweight`, `pharmacokinetics`, `bioequivalence`, `elderly`, `drug
   interactions`, ...) and, less commonly, whole sentences of study
   description text that ended up in the Condition field. Two checks, both
   testable in isolation: (a) exact match against a small curated stoplist
   of real junk terms found in the metformin pull, (b) a length heuristic —
   a "condition" longer than 8 words is treated as description text, not a
   disease name. Wired into `scoring.py`'s `group_documents_by_pair`, so
   junk is dropped before it ever reaches scoring/signal output — not just
   hidden downstream.
2. **Single-token genericity guard** (`is_too_generic_to_match`, same
   file). Guards the false-positive risk flagged when Step 5 shipped: a
   bare, single-token, very generic observed disease (e.g. just "cancer")
   could otherwise match against any approved text that happens to mention
   that word anywhere (e.g. an unrelated boxed-warning sentence), even
   though the drug isn't actually approved for that disease. Implemented
   as a short exclude-list (`cancer`, `disease`, `syndrome`, `tumor`,
   `tumour`, `disorder`, `carcinoma`, `neoplasm`, `infection`, `condition`)
   checked only when the observed term reduces to exactly one token —
   chosen over a blanket "require ≥2 tokens" rule so legitimate single-word
   diseases (`obesity`, `dengue`, `psoriasis`) can still match normally.
   Wired into `diseases_match` itself (returns `False` immediately for a
   bare generic single term, regardless of what the approved text says).

**Both are separate, testable functions** — neither touches the core
token-subset matching logic in `diseases_match` that Step 5 already proved
works on the two real cases.

**Tests:** `backend/tests/test_disease_matching.py` gained 12 new tests —
`is_junk_condition` tested against every real junk term pulled from the
Step 3 metformin run (`healthy`, `efficacy`, `overweight`, full sentence
fragments, etc.) plus real disease conditions confirmed to pass through
unfiltered; `is_too_generic_to_match` tested for bare generic terms
(blocked), multi-token terms containing a generic word (`breast cancer`,
unblocked), specific single-token diseases (`obesity`, `dengue`,
unblocked), and an explicit spurious-match regression test — a bare
"cancer" against unrelated approved text that happens to mention cancer in
passing must NOT match. All passing — 43/43 tests pass project-wide.

**Re-verified against the real Step 5 data:** re-ran
`scripts/run_pipeline.py` against the same 557 real documents. Signal count
dropped from 301 to 265 (36 junk-condition signals removed, including the
`healthy`/`efficacy` ones originally flagged). Both watch pairs still
behave correctly: metformin/pancreatic cancer still flagged, sildenafil/PAH
still correctly discarded.

## Judgment calls made in Step 5 (flagging, not deciding silently)

- **How aggressive the matching should be:** token-subset containment was
  chosen over plain substring matching (too strict — misses the PAH case)
  or full fuzzy/similarity scoring (harder to reason about, no ontology
  data available). This is a *conservative-ish* middle ground, not a
  principled choice — worth revisiting if real data surfaces more edge
  cases.
- **Staging-qualifier list is hand-picked, not exhaustive.** Currently:
  `stage`, `i`-`vi`, `metastatic`, `recurrent`, `advanced`, `relapsed`,
  `refractory`, `unresectable`, `localized`, `grade`. Real ClinicalTrials.gov
  condition strings almost certainly use other qualifiers this list doesn't
  cover yet (e.g. "early-stage", "de novo", "treatment-naive"). Extend the
  set in `disease_matching.py` as more are spotted, rather than trying to
  guess them all up front.
- **Known false-positive risk, not yet guarded against:** a single-token,
  generic observed disease (e.g. just `"cancer"`) could spuriously match
  against a long openFDA paragraph if that word appears anywhere in it
  (e.g. in a boxed warning about cancer risk, unrelated to the drug's
  actual approved use) — documented directly in `diseases_match`'s
  docstring. Didn't add a minimum-token-count guard because it's unclear
  what threshold is right without seeing it cause an actual bad result;
  flagging for the user to weigh in on if/when it shows up.
- **Matching is still not ontology-aware** (no MeSH/RxNorm/UMLS lookup) —
  this heuristic handles the two concrete cases we've seen, not the general
  problem. Still the single biggest simplification in the pipeline.

## What's actually built right now (Step 6 detail)

**What it does:** pulls real bioRxiv/medRxiv preprint titles+abstracts
mentioning a given drug, runs a local biomedical NER model over each one to
pull out disease mentions, and turns each (paper, extracted disease) pair
into a `Document` — same shared shape as ClinicalTrials.gov, stored in the
same `documents` table, participating in the same comparison engine, no
special-casing needed downstream.

**Judgment call: how "bioRxiv/medRxiv ingestion" actually works.** Neither
bioRxiv nor medRxiv offers a public full-text/keyword search API — their
own API (`api.biorxiv.org`) only lists papers by date range or looks up one
paper by DOI, with no way to ask "papers mentioning metformin." (Confirmed
directly: scanning ~300 real medRxiv papers from a Jan–Mar 2025 date window
via that API turned up zero metformin mentions — date-range scanning alone
isn't a workable discovery method at any reasonable request budget.)
**Europe PMC** (europepmc.org, EMBL-EBI, free/no-login) indexes the same
bioRxiv/medRxiv preprints and *does* support keyword search plus a
`PUBLISHER` filter — every result returned is still a genuine bioRxiv or
medRxiv paper (same title, DOI, abstract, publish date as the original),
just discovered through Europe PMC's search index instead of bioRxiv's own
site, which can't do that search. This is flagged here as a judgment call,
not silently substituted — see `app/ingestion/biorxiv.py`'s module
docstring for the same explanation in the code.

**NER model:** `en_ner_bc5cdr_md`, scispaCy's model trained on the BC5CDR
corpus for biomedical entity recognition (DISEASE + CHEMICAL labels). Local
model, no LLM APIs — per the project's explicit constraint. It's a large
download (~120MB) and not resolvable as a normal PyPI dependency; installed
via its direct release URL (see `requirements.txt`).

**Files:**
- `backend/app/ingestion/biorxiv.py` — talks to Europe PMC's search API
  (cursor-paginated), strips HTML structure tags from abstracts, runs NER,
  and converts extracted DISEASE entities into `Document` objects (one per
  unique disease per paper). `load_ner_model()` lazily loads and caches the
  scispaCy model (loading it per-call would be far too slow).
- `backend/scripts/ingest_biorxiv.py` — the runnable sanity-check script
  requested for this step. Prints a few real abstracts next to what NER
  extracted from them, for direct eyeballing. Run with
  `py scripts/ingest_biorxiv.py` from `backend/` (needs the NER model
  installed first — see `requirements.txt`).
- `backend/tests/test_biorxiv.py` — 11 new automated tests covering HTML
  stripping, date parsing, entity extraction/dedup, and document conversion
  (missing DOI, non-bioRxiv/medRxiv publisher, no disease entities). Tests
  use a hand-crafted fake NER model (a tiny stand-in returning pre-registered
  entities) instead of the real 120MB model, so the suite stays fast and
  doesn't require the model to be installed to run. All passing — 54/54
  tests pass project-wide.
- No new DB table needed — bioRxiv/medRxiv documents reuse Step 3's
  `documents` table and `upsert_documents`/`load_all_documents` unchanged;
  `Document.source` already supports `"biorxiv"`/`"medrxiv"` per
  `shared/schema.md`.

**Live sanity check results (2026-08-19), pulling real Europe PMC data
capped at 15 preprints per drug:**

- metformin: 15 preprints found, NER extracted 52 drug-disease documents
  (52 new, 0 duplicates). Real examples pulled from an actual medRxiv
  abstract: `dementia`, `cognitive impairment`, `frailty`,
  `glucose intolerance` — plausible repurposing-adjacent signals, exactly
  the kind of "early hint before FDA approval" this project is trying to
  surface.
- sildenafil: 15 preprints found, NER extracted 68 drug-disease documents.
  One bioRxiv basic-science abstract about arteriolar cGMP signaling
  correctly produced *no* disease entities (it's not about a specific
  disease) — a good sign the model isn't hallucinating diseases into
  unrelated text.
- Re-ran `scripts/run_pipeline.py` against all three sources combined: 677
  documents total (557 from Step 3 + 120 from Step 6), 351 signals
  produced. **Both Step 5 watch pairs still correct:** metformin/pancreatic
  cancer still flagged (score 0.720), sildenafil/pulmonary hypertension
  still correctly discarded as already approved.

**New known issue found in this step:** one NER extraction was clearly
wrong — from the DPP cognitive-outcomes abstract, the model tagged
`"alzheimer's coordinating center uniform dataset version 3."` (a dataset
name, not a disease) as a DISEASE entity. Not filtered by Step 5's
`is_junk_condition` (it's under the 8-word cutoff and isn't in the
ClinicalTrials-derived stoplist, which was never meant to cover NER
artifacts). Not fixed here — flagged as a Step 6-specific data-quality
follow-up, same "extend the filter as more junk is spotted" approach as
Step 5's stoplist, not a reason to block shipping ingestion.

## Step 7 status: deliberately deferred, not skipped

The user explicitly chose to defer Step 7 (a scheduler that re-runs Steps
3/4/6 ingestion + Step 5 comparison on a fixed interval) in favor of Step 8,
reasoning that a working, visually convincing dashboard matters more for a
demo than an unattended background poller. Nothing about Step 7 is
foreclosed — the orchestration it needs is just "call the existing
`ingest_drug()` functions from Steps 3/4/6, then `run_comparison()`, on a
timer," reusing modules as-is, no new logic. Pick it up whenever
live/continuously-refreshing data becomes the priority again.

## What's actually built right now (Step 8 detail)

**What it does:** a read-only FastAPI backend serving the signals already
produced by Steps 3-6's ingestion + Step 5's comparison/scoring engine, and
a React dashboard that visualizes them. No new ingestion or comparison
logic — Step 8 is presentation over the existing pipeline's output.

### Backend

- `backend/app/schemas/api.py` — `SignalOut`, a response shape that wraps
  the existing `Signal` model with a few fields the frontend needs and
  shouldn't have to compute client-side: `num_independent_sources`,
  `source_breakdown` (counts per source type), `first_detected` (earliest
  supporting-document date), and `sources` (a list of `SourceLink`s — real
  URLs back to ClinicalTrials.gov/Europe PMC/openFDA). All computed by
  reading a `Signal`'s existing `supporting_documents` — no new business
  logic.
- `backend/app/main.py` — the FastAPI app. Signals are computed **once at
  startup** (via `run_comparison` over everything in `arbitrage.db`) and
  held in memory, not recomputed per request — there's no live re-polling
  yet (that's the deferred Step 7), so redoing a ~350-signal comparison on
  every request would just be wasted work against data that hasn't
  changed. Endpoints:
  - `GET /signals` — every signal, sorted by score (score sort already
    happens in `run_comparison`).
  - `GET /signals/{drug}` — filtered to one drug (case-insensitive), 404 if
    none found.
  - `GET /search?q=` — substring match against drug or disease.
  - `GET /health` — trivial liveness check.
- `backend/tests/test_api.py` — 11 new tests using FastAPI's `TestClient`
  against signals built from the Step 2 fixture (not the real DB, so the
  suite doesn't depend on ingestion scripts having been run). Covers shape
  of a signal response, sorting, drug filtering (incl. case-insensitivity
  and 404), and search (drug match, disease match, empty query, no match).
  All passing — 65/65 tests pass project-wide.
- `requirements.txt` gained `fastapi`, `uvicorn[standard]`.
- Run with: `uvicorn app.main:app --reload` from `backend/`.

### Frontend

`frontend/` is a new Vite + React + TypeScript app (previously an empty
placeholder directory). Design direction, per explicit instruction: lean
into "arbitrage" as a trading/market terminal, not a generic admin
dashboard — dark theme, monospace numerals, one consistent visual system.

- **Ticker strip** — a continuously scrolling marquee (pure CSS animation,
  pauses on hover) across the top showing recent signals as
  `drug → disease  score`, color-coded by confidence tier.
- **Opportunity cards** — one per signal: drug → disease pair, score
  rendered like a price in monospace with a High/Med/Low confidence badge,
  independent-source count styled like trading volume, and a small
  segmented bar + legend showing the source-type breakdown (trial vs.
  bioRxiv vs. medRxiv). Clicking a card expands it in place to show why
  it's flagged (reason chips), what the drug is already approved for, and
  the actual supporting documents as clickable rows linking to the real
  ClinicalTrials.gov/Europe PMC/openFDA source.
- **Network graph tab** — `react-force-graph-2d`, drug and disease nodes
  connected by score-colored/width-scaled edges. Judgment call made and
  then corrected during testing: the default force layout clustered
  everything unreadably once there were more than a handful of nodes (this
  project's real data has 339 distinct diseases). Fixed by widening the
  charge/link forces, auto-zoom-to-fit after the layout settles, and only
  rendering disease labels once zoomed in past a threshold (drug labels
  always render — there are only ever one or two). Verified visually in a
  real browser: filtering to one drug produces a clean "sunburst" of its
  disease connections; the unfiltered view clearly shows both drug hubs.
- **Search/filter bar** — filters both the card grid and the network graph
  by drug/disease substring, backed by the same `/search`-shaped logic
  used against locally-loaded signals (client-side filter over the
  already-fetched `/signals` payload, not a separate request per
  keystroke).
- One accent color (`--accent`, green) for high confidence, amber for
  medium, a muted blue for low — used consistently across score badges,
  ticker text, card accents, source-breakdown bars, and graph edges/legend
  so the three views read as one system, not three different tools stapled
  together.

**Files:** `frontend/src/api.ts` (typed fetch client), `frontend/src/scoring.ts`
(score-tier bucketing + source labels, shared across components — see
judgment call below), `frontend/src/index.css` (design tokens + all
styling), `frontend/src/App.tsx`, `frontend/src/components/{TickerStrip,SearchBar,OpportunityCard,NetworkGraph}.tsx`.

Run with: `npm install && npm run dev` from `frontend/` (expects the API at
`http://127.0.0.1:8000`, overridable via `VITE_API_BASE`).

**Judgment call: score-tier thresholds.** The dashboard buckets scores into
High (&ge;0.7) / Medium (0.4-0.69) / Low (&lt;0.4) for badge coloring and the
ticker. This is a **display-only** choice in `frontend/src/scoring.ts`, not
a change to `app/core/scoring.py`'s actual scoring model — picked to look
reasonable against the real score distribution (many capped-at-1.0 signals,
a long tail down to ~0.3), not derived from any statistical validation.
Worth revisiting once there's a sense of what score actually correlates
with a real repurposing outcome.

**Verified end to end (2026-08-19):** ran the real backend
(`uvicorn app.main:app`) against the real `arbitrage.db` (677 documents, 351
signals) and the real frontend (`npm run dev`) together in an actual Chrome
browser (via browser automation, not just `curl`/unit tests):
- Signals view loads all 351 signals, correctly sorted, with working
  card expansion showing reason chips, approved-for text, and clickable
  source links.
- Search for `"pancreatic"` correctly surfaces `Stage IV Pancreatic Cancer`
  (score 0.720) — the exact Step 5 fix, visible and working in the UI.
- Network graph, filtered to `sildenafil`, renders a legible sunburst of
  ~50 disease connections around the drug node; unfiltered view shows both
  drug hubs clearly.
- No console errors during any of the above.
- `npm run build` (TypeScript + Vite production build) succeeds cleanly.

**Known rough edge, not fixed:** `approved_for` text (from openFDA's raw
paragraph — see Step 4/5) is truncated for display in the expanded card
(`truncate()` in `OpportunityCard.tsx`, ~260 chars) rather than fixed at the
data layer, since the backend intentionally keeps the full raw text as the
source of truth. Fine for the demo; a real product would probably want a
cleaner "approved for: X, Y, Z" summary, which circles back to the
still-open "openFDA text isn't split into individual diseases" limitation
from Steps 4/5.

## What's actually built right now (Step 10 detail)

**The problem this step fixes.** Every source-ingestion script
(`scripts/ingest_clinicaltrials.py`, `scripts/ingest_biorxiv.py`,
`scripts/ingest_openfda.py`) had a literal `DRUGS_TO_INGEST = ["metformin",
"sildenafil"]` at the top, and every `ingest_drug(drug: str, ...)` function
in `app/ingestion/{clinicaltrials,biorxiv,openfda}.py` *required* a drug
name as input — there was no code path anywhere that discovered a drug
name from the data itself. ClinicalTrials.gov's query was
`query.intr: drug` (an intervention filter keyed on a known drug), and
Europe PMC's query embedded the drug name directly (`f"{drug} AND
SRC:PPR..."`). So the system wasn't "capped at 2" by a stray slice or
off-by-one — it was structurally two-drug-only: nothing upstream of those
three-line lists could have produced a third drug even if the cap were
raised, because there was no discovery mechanism, only per-drug lookup.
`backend/data/known_cases.json` was **not** part of this problem — audited
first and confirmed it's a hand-written test fixture, loaded only by
`app/core/fixtures.py` for `tests/test_scoring.py` and
`demo_scoring.py`, never touched by any ingestion script or the API. Left
unchanged. The frontend was also audited and found to have zero hardcoded
drug-count assumptions — `cards-grid`, the ticker, the network graph, and
the stat chips all already compute from however many signals `/signals`
returns; no frontend change was needed for this step.

**The fix, source by source:**
- **ClinicalTrials.gov** (`app/ingestion/clinicaltrials.py`): new
  `discover()` entry point queries *all* interventional studies posted
  within a rolling window (`filter.advanced=AREA[StudyFirstPostDate]RANGE[...]`,
  no `query.intr`), and `extract_drug_names()` pulls every DRUG-type
  intervention name off each study's `armsInterventionsModule` — the drug
  names come FROM the results now, not from a caller argument.
  `parse_study_to_documents_discovery()` pairs every discovered drug with
  every condition the study lists. The old `ingest_drug(drug)` /
  `fetch_raw_studies(drug)` functions are kept as-is (tests still cover
  them; nothing else calls them anymore).
- **Europe PMC (bioRxiv/medRxiv)** (`app/ingestion/biorxiv.py`): new
  `discover()` queries the same `PUBLISHER:"bioRxiv" OR
  PUBLISHER:"medRxiv"` filter plus a `FIRST_PDATE` recency window, again
  with no drug keyword. `extract_entities()` was generalized from the old
  disease-only `extract_diseases()` to accept a label, and a new
  `extract_drugs()` runs the *same already-installed* `en_ner_bc5cdr_md`
  model with the `CHEMICAL` label to pull drug mentions out of the
  abstract — no second NER model, no LLM, just the other label the
  existing model already supports.
  `parse_preprint_to_documents_discovery()` pairs every drug entity found
  with every disease entity found in the same abstract.
- **openFDA** (`app/ingestion/openfda.py`): unchanged in shape (it
  genuinely needs a drug name to look up a label — this was never the
  problem). What changed is the *caller*: `app/ingestion/discovery.py`'s
  `run_discovery()` now calls `openfda.ingest_drug()` once per drug
  discovered by the two steps above in that run, not for a fixed list.

**Persistent known-drugs cache** (`app/models/known_drug.py`,
`upsert_known_drug`/`load_all_known_drugs` in `app/ingestion/store.py`):
one row per canonical drug entity, keyed on a normalized name; re-running
discovery merges newly-seen surface forms into the same row (`last_seen`
bumped, variant list appended) instead of resetting the table. This is
what "reactive openFDA lookup for every discovered drug" is built on top
of, and what makes the cache genuinely additive across runs rather than a
snapshot of one run's results.

**Normalization/dedup** (`app/core/drug_normalization.py`,
`normalize_drug_name`): extends the existing lowercase/strip pattern
already used by `Document.normalized_drug()` (not a second parallel
system) with heuristic stripping of salt/dosage-form words ("hydrochloride",
"500mg", "er tablet", ...) and ClinicalTrials.gov's filler intervention
phrasing ("Dose reduction of X" -> "X"), so
`"Metformin Hydrochloride 500mg"`, `"metformin HCl ER Tablet"`, and
`"Metformin"` all collapse to the same `known_drugs` row. Also does a
best-effort RxNorm CUI lookup via RxNav's free, no-login REST API
(`resolve_rxnorm_id`, cached, never raises — a network failure there just
leaves `rxnorm_id` null, it doesn't block ingestion).

**Pagination:** already existed in both `clinicaltrials.py` and
`biorxiv.py` (page-token / cursor-mark loops) from Steps 3/6 — discovery
mode reuses the exact same pagination loops, just with a broader query and
no drug filter. Verified against ClinicalTrials.gov (a source known to
paginate) by setting `ARB_PAGE_SIZE` below `ARB_MAX_RESULTS_PER_SOURCE`
and confirming `nextPageToken` is actually followed across multiple
requests rather than only reading page one.

**Configuration** (`app/core/config.py`): four env-var-driven knobs, all
with defaults, none requiring a code change to take effect —
`ARB_MAX_RESULTS_PER_SOURCE` (default 10), `ARB_TIME_WINDOW_DAYS` (default
90), `ARB_MIN_CONFIDENCE_SCORE` (default 0.0, wired into
`run_comparison`'s new `min_score` filter), `ARB_OPENFDA_LABELS_PER_DRUG`
(default 10), `ARB_PAGE_SIZE` (default 50). Acceptance test run below.

**Fallback behavior** (`app/models/ingestion_status.py`,
`record_source_status`/`load_source_statuses`, new `GET /status`
endpoint): every discovery attempt — success or `httpx.HTTPError` — writes
one row per source recording status/message/count. A source outage shows
up as `"status": "error"` with the real exception message, both in
`scripts/run_pipeline.py`'s printed report and via `/status`, instead of
silently looking like "this source just happened to find nothing." This
was exercised for real, not just theoretically: mid-build, Europe PMC's
API returned a transient `503 Service Temporarily Unavailable` on a live
run, and the pipeline correctly reported `[europepmc] SOURCE UNAVAILABLE —
503 ...` and continued with ClinicalTrials.gov/openFDA's real results
rather than falling back to `known_cases.json` or pretending the source
had returned zero.

**Backend API at scale:** `/signals`, `/signals/{drug}`, `/search` needed
no shape changes — they were already plain list comprehensions/filters
over `app.state.signals` with no hardcoded size assumption. Verified this
holds by running the real pipeline (see below) and confirming all three
endpoints still work correctly with signals spanning 15+ distinct drugs
instead of 2. Added `tests/test_scoring.py`'s
`test_scales_to_many_distinct_drugs_without_capping_result_count` (50
synthetic drugs -> 50 signals, none dropped) as a permanent regression
guard against a future accidental cap.

**Files:**
- New: `app/core/config.py`, `app/core/drug_normalization.py`,
  `app/ingestion/discovery.py`, `app/models/known_drug.py`,
  `app/models/ingestion_status.py`.
- Changed: `app/ingestion/clinicaltrials.py` (added `discover()`,
  `extract_drug_names()`, `parse_study_to_documents_discovery()`,
  `fetch_raw_studies_broad()`), `app/ingestion/biorxiv.py` (added
  `discover()`, `extract_entities()`/`extract_drugs()`,
  `parse_preprint_to_documents_discovery()`, `fetch_raw_preprints_broad()`),
  `app/ingestion/openfda.py` (default limit now reads from config),
  `app/ingestion/store.py` (added known-drug and source-status
  upsert/load functions), `app/core/scoring.py` (`run_comparison` gained
  `min_score`), `app/main.py` (added `GET /status`), `app/models/db.py`
  (registers the two new tables), `scripts/ingest_clinicaltrials.py` /
  `scripts/ingest_biorxiv.py` (now discovery-mode, no drug list) /
  `scripts/ingest_openfda.py` (now reads the known-drugs cache instead of
  a fixed list), `scripts/run_pipeline.py` (now the full orchestrator:
  runs discovery across all three sources, then comparison, then the
  regression check — previously assumed ingestion had already happened
  and only ran the comparison step).
- New tests: `tests/test_config.py`, `tests/test_drug_normalization.py`,
  `tests/test_known_drugs_store.py`, `tests/test_discovery_parsing.py`,
  plus two additions to `tests/test_scoring.py`
  (`test_min_score_filters_low_confidence_signals`,
  `test_scales_to_many_distinct_drugs_without_capping_result_count`). All
  passing — 85/85 tests pass project-wide (up from 65).

**Verified at scale, real live data (2026-08-19), two runs of
`scripts/run_pipeline.py` against the same accumulating `arbitrage.db`:**

| | `ARB_MAX_RESULTS_PER_SOURCE=10` | `ARB_MAX_RESULTS_PER_SOURCE=50` |
|---|---|---|
| ClinicalTrials.gov | OK — 9 documents found | OK — 25 documents found |
| Europe PMC | OK — 10 documents found (transient 503 hit once mid-build, correctly reported, retried successfully) | OK — 165 documents found |
| openFDA | OK — 13 drugs looked up reactively, 39 approved indications inserted | OK — 55 drugs looked up reactively, 34 new approved indications inserted |
| Distinct drugs discovered this run | 13 | 55 |
| Documents / approved indications (accumulated) | 696 documents, 59 approved indications | 867 documents, 179 approved indications |
| Total signals (accumulated) | 370, across 15 distinct drugs | 535, across 56 distinct drugs |
| Regression check | metformin/pancreatic cancer FLAGGED (0.720); sildenafil/pulmonary hypertension correctly NOT flagged | same — metformin/pancreatic cancer FLAGGED (0.720); sildenafil/pulmonary hypertension correctly NOT flagged |

No code was changed between the two runs — only the `ARB_MAX_RESULTS_PER_SOURCE`
env var (10 -> 50), per the acceptance test in the brief. Signal count and
distinct-drug count both scaled up with it (370 -> 535 signals, 15 -> 56
drugs); the two original regression pairs held at both limits, now two
entries among 56 drugs rather than the entire dataset.

**Known limitations, flagged rather than silently accepted:**
- The bioRxiv/medRxiv CHEMICAL-label extraction picks up some non-drug
  chemical/lab terms on general-biology preprints (`"glucose"`,
  `"creatinine"`, `"snp"`, `"ai"`) — same class of NER-artifact issue
  already documented for Step 6's DISEASE extraction (the dataset-name
  false positive). Not filtered here for the same reason Step 6's version
  wasn't: no curated stoplist exists yet for this specific failure mode.
  Flagged as a follow-up, same "extend the filter as more junk is spotted"
  approach as `is_junk_condition`.
- ClinicalTrials.gov intervention names are often verbose/free-text
  ("Dose reduction of lezertinib", "Supplementation of magnesium
  lactate") — `normalize_drug_name`'s filler-phrase stripping handles the
  patterns seen so far but is a hand-picked list, not exhaustive, same
  spirit as the staging-qualifier list in `disease_matching.py`.
- Europe PMC's search API showed real intermittent 502/503/504 errors
  during testing (not a bug in this codebase — their gateway under a
  broad, unfiltered-by-drug query). The fallback-behavior fix means this
  surfaces clearly instead of being mistaken for "no new preprints," but
  it does mean a given run can genuinely come back with 0 Europe PMC
  documents through no fault of the query.
- RxNorm enrichment (`resolve_rxnorm_id`) is best-effort and un-tested
  against exotic drug names (combination products, biologics) — it's a
  nice-to-have on the known-drugs cache, not load-bearing for any
  comparison/scoring logic.

## Next step

Checking in with the user before deciding what's next — either picking up
the deferred Step 7 (scheduler, now more valuable since discovery runs are
meant to repeat over time), or hardening the known-limitations above
(NER-artifact filtering for CHEMICAL entities, a broader intervention-name
filler-phrase list).

## Known issues / shortcuts so far

- No scheduler yet (Step 7 deliberately deferred — see above). Signals are
  computed once at API startup from whatever's in `arbitrage.db` at that
  moment; picking up new data means re-running the Step 3/4/6 ingestion
  scripts and restarting the API. Fine for a demo, not a "live" system yet.
- The dashboard's High/Medium/Low score-tier thresholds are a display-only
  judgment call (`frontend/src/scoring.ts`), not a validated mapping to
  real repurposing likelihood — see Step 8 detail above.
- `approved_for` text shown in the UI is openFDA's raw paragraph, truncated
  for display rather than cleaned at the data layer — same underlying
  limitation as the openFDA free-text issue from Steps 4/5, now visible in
  the frontend too.
- Disease-name matching is now staging-qualifier-aware token matching
  (Step 5), not ontology-aware. It fixes the two concrete cases seen so far
  (metformin/pancreatic cancer, sildenafil/PAH) but is still a hand-picked
  heuristic, not MeSH/RxNorm/UMLS-backed — see "Judgment calls made in Step
  5" above for remaining sharp edges (unhandled staging qualifiers). The
  single-token false-positive risk is now guarded (see "Data-quality fixes"
  above) — not eliminated for every conceivable case, but the concrete risk
  flagged after Step 5 is fixed and tested.
- openFDA's `indications_and_usage` is stored as raw free text, not split
  into individual disease names. A single label can (and often does)
  describe more than one approved use in one paragraph. Step 5's matcher
  works against the whole paragraph via token-subset containment rather
  than needing it pre-split, so this is no longer blocking — but it's still
  worth revisiting if paragraph-level matching ever produces a bad result.
- Junk trial-condition filtering (`is_junk_condition`) is a curated
  stoplist + a length heuristic, not exhaustive. It catches every real junk
  term found so far (`healthy`, `efficacy`, `overweight`, etc.) but a new
  ClinicalTrials.gov study could introduce a short, plausible-looking junk
  term the stoplist doesn't know about yet (e.g. a new eligibility phrase).
  Extend `JUNK_CONDITION_TERMS` in `disease_matching.py` as more are
  spotted, same approach as the staging-qualifier list.
- openFDA ingestion is capped at 10 labels/drug for the sanity check; not
  exhaustive (metformin alone has hundreds of labeled products, many
  combination drugs). Fine for now — same reasoning as Step 3's 200-study
  cap.
- ClinicalTrials.gov ingestion is capped at 200 studies/drug for the demo
  sanity check; not exhaustive. Fine for now — Step 5 can raise the cap
  once the comparison engine is wired up and we know what "enough data"
  looks like for the demo.
- Some ClinicalTrials.gov studies still list the drug's own name (e.g.
  `"metformin"`) or outcome-metric-looking names (e.g. `"bct rate"`, `"pcr
  rate"`) as if they were diseases — these aren't on the junk stoplist yet
  since they weren't in the original flagged set and are harder to catch
  with a generic heuristic (they don't look like sentences and aren't from
  a small fixed vocabulary). Left as a follow-up if they turn out to add
  noticeable noise.
- bioRxiv/medRxiv discovery goes through Europe PMC's search index rather
  than bioRxiv's own site (which can't do keyword search at all) — see
  Step 6 detail above for why. Worth knowing if data ever looks
  "off"/incomplete: it's bounded by what Europe PMC has indexed and how its
  relevance/keyword matching works, not by what's literally newest on
  bioRxiv/medRxiv.
- The scispaCy NER model (`en_ner_bc5cdr_md`) occasionally mislabels
  non-disease text as a DISEASE entity — confirmed once on real data (a
  dataset name, `"alzheimer's coordinating center uniform dataset version
  3."`, tagged as a disease). Not filtered — flagged as a Step 6-specific
  follow-up to `is_junk_condition` if more NER artifacts like this turn up.
- bioRxiv/medRxiv ingestion is capped at 15 preprints/drug for the sanity
  check; not exhaustive. Fine for now, same reasoning as the other two
  sources' caps.
- `frontend/` directory exists but is empty — React app not started.

## The TheraLens pivot (2026-08-19) — backend-only phase

**What changed, conceptually.** The product concept moved from "browse a
ranked list of drug-disease signals" to "TheraLens — patient-context-aware
drug repurposing intelligence." A user creates a clinical **Case** (primary
condition, comorbidities, current medications), and the system analyzes
which of the existing repurposing signals are relevant to *that specific
patient context* — including safety/context flags, not just a ranked drug
list. This phase is backend-only; the frontend was not touched.

**Explicit non-goal, honored:** no migration to a graph database. Every new
relationship (Case, CaseCondition/CaseMedication, and the drug-vs-label
safety fields) is modeled as plain relational tables/join tables in the
same SQLite database everything else already uses. A "graph" is a later-
phase UI rendering concern, not a backend architecture requirement — the
existing engine (`scoring.py`, `disease_matching.py`) already models
drug/disease relationships as rows and index dicts, and this phase extends
that pattern rather than replacing it.

**Audit-first, reuse-heavy — nothing rebuilt.** Before writing anything new,
`disease_matching.py`, `scoring.py`, `openfda.py`, and `store.py` were read
in full (not skimmed). The result: almost everything needed already
existed.
- The drug-discovery pipeline (`run_comparison` in `scoring.py`) already
  produces every "drug being studied for a disease it's not approved for"
  pairing, with a score, reasons, supporting documents, and known approved
  indications. TheraLens's case-analysis engine calls this function
  directly and unmodified — it does not reimplement disease discovery.
- The token-subset disease matcher (`diseases_match` in
  `disease_matching.py`) already solves "does this disease term appear in
  this drug-label paragraph" for indications_and_usage. The exact same
  function is reused, unmodified, to check a case's primary condition
  against a signal's disease text (`app/core/case_analysis.py`'s
  `_condition_matches`) — and the same token-subset logic is reused a
  second time (via a small new wrapper, `check_comorbidity_conflict`) to
  check comorbidity terms against contraindications/warnings text instead
  of indications text. Same problem, same solution, different label field.
- `openfda.py`'s label-parsing pattern (fetch → join text paragraphs
  as-is → store raw, no fabricated structuring) was extended, not replaced,
  to also capture `contraindications`, `warnings`
  (`warnings_and_precautions` as fallback), and `drug_interactions` — three
  new optional fields on `ApprovedIndication`, populated the exact same way
  `indications_and_usage` already was.

### 1. Case model

New tables (`app/models/case.py`), all free-text, dynamic input — no
hardcoded disease/drug lists anywhere in this feature, per the brief:
- `cases` — `id`, `primary_condition`, `created_at`, `saved` (bool).
- `case_conditions` — many-to-one to `cases`, one free-text comorbidity per
  row.
- `case_medications` — many-to-one to `cases`, one free-text current
  medication per row.
- `case_analyses` — the *last* analysis result for a case, stored as a JSON
  blob (overwritten on each re-analyze, not appended — a history table
  wasn't asked for and wasn't built).

Case creation (`create_case` in `app/ingestion/store.py`) normalizes
condition/comorbidity text the same way every other disease mention in this
project already is (`app.core.scoring.normalize` — lowercase + whitespace
collapse) and medication text the same way every other drug mention already
is (`normalize_drug_name` from Step 10 — strips salt/dosage/filler words so
"Metformin 500mg" and "metformin" collapse to one entity). A disease/drug
*search* endpoint (autocomplete-style lookup) is explicitly out of scope for
this phase — noted in the brief as a frontend concern for later.

### 2. Safety/context data — extended, not rebuilt

`ApprovedIndication` (`app/schemas/document.py`) gained three optional raw-
text fields: `contraindications`, `warnings`, `drug_interactions`. openFDA's
label API already returns these alongside `indications_and_usage`;
`openfda.py`'s `parse_label_to_indication` now captures all three via a new
`_join_field` helper (same paragraph-joining approach already used for
indications — no extraction, no fabricated structuring, stored as-is or
left `None` if openFDA didn't return the field). `approved_indications`
gained matching nullable columns
(`app/models/approved_indication.py`). Since `backend/data/arbitrage.db` is
an existing, already-populated file (not recreated from scratch), a small
migration helper was added to `app/models/db.py`
(`_migrate_add_missing_columns`) that does a plain, idempotent
`ALTER TABLE ... ADD COLUMN` for any column present in the ORM model but
missing from an existing SQLite table — SQLAlchemy's `create_all` only
creates *new* tables, it never alters existing ones.

Scope, explicitly (per the brief): **v1 only checks candidate-drug-vs-
comorbidities.** Current-medication pairwise drug-drug interaction checking
(does the case's existing medication list conflict with a *candidate* drug)
is **not** attempted in this phase — see "Documented limitation" below,
this is logged as a decision, not a silent gap.

### 3. Case-analysis engine (`app/core/case_analysis.py`)

`analyze_case(primary_condition, comorbidities, documents, approved,
today=None)`:

1. Calls `run_comparison(documents, approved)` unmodified — the existing
   scoring engine produces every not-yet-approved drug-disease `Signal`.
2. Filters to signals whose `disease` matches the case's `primary_condition`
   via `diseases_match`, checked in **both directions**
   (`diseases_match(a, b) or diseases_match(b, a)`) — unlike the
   indications-vs-observed case, a case's free-text condition and a
   signal's free-text disease mention are both arbitrary-specificity
   strings; neither side can be assumed to be "the more general one," so
   the existing one-directional matcher is applied symmetrically rather
   than modified.
3. For each surviving candidate drug, runs the comorbidity-conflict check
   (`app/core/context_check.py`) against every one of the case's
   comorbidities individually, against every openFDA label already ingested
   for that drug, combining multi-label results per comorbidity
   (`combine_states`: a real conflict found on any one label always wins;
   a clean check on at least one label beats having no data at all).

**Three-state comorbidity check** (`check_comorbidity_conflict` in
`app/core/context_check.py`), the exact interpretation used, spelled out
because the brief calls for "explainable, not a black box":
- `conflict_detected` — the drug has real contraindications/warnings text
  ingested, *and* the comorbidity's tokens are a subset of that text's
  tokens (same token-subset rule as `diseases_match`). Evidence returned is
  the actual matching sentence, extracted verbatim from the real label text
  (falls back to the whole field if the match spans a list item rather than
  one sentence) — never generated/fabricated text.
- `no_conflict_detected` — the drug **has** contraindications/warnings text
  ingested (so a check was actually possible), and the comorbidity's tokens
  are *not* found in it.
- `insufficient_evidence` — the drug has **no** contraindications/warnings
  text ingested at all (openFDA didn't return the field for any of its
  labels), so there's nothing to check against. This is deliberately kept
  distinct from `no_conflict_detected`: "we checked and it's clear" and "we
  had nothing to check" are different claims, and conflating them would
  mean silently defaulting missing data to "no concern" — exactly what the
  brief prohibits.

**Research Priority formula** (`app/core/case_analysis.py`, constants at
the top of the file):

```
research_priority_score = clip(
    evidence_strength_score            # signal.score, from scoring.py's run_comparison — unmodified
    - conflict_penalty
    - insufficient_evidence_penalty,
    0.0, 1.0
)

conflict_penalty = min(0.30, 0.15 * num_comorbidities_in_conflict_detected)
insufficient_evidence_penalty = min(0.10, 0.03 * num_comorbidities_in_insufficient_evidence)
```

Rationale for the two different per-hit weights: a detected
contraindication/warning conflict is *real negative evidence* and should
meaningfully lower research priority (0.15 per comorbidity, capped at 0.30
so a case with many comorbidities doesn't trivially zero out every
candidate). Missing/insufficient label data is *not* negative evidence —
it's uncertainty about a real signal — so it gets a much smaller per-hit
penalty (0.03, capped at 0.10): enough that a well-documented, clean
candidate ranks above an otherwise-identical candidate we simply couldn't
check, without punishing a candidate for a data gap that isn't evidence
against it. `no_conflict_detected` comorbidities apply no penalty at all.
This is a hand-tuned heuristic, same spirit (and same honesty about it) as
`scoring.py`'s existing weights — not a calibrated statistical model.

**"Why surfaced" / "why flagged" reasoning trail:** every candidate carries
`reasoning_trail: list[str]`, built in exactly the order the brief
specifies — known indication → new disease association → supporting
studies/trials (real `source:source_id` pairs) → evidence strength score →
one line per comorbidity context-check result → final research priority
score. This is returned by the API as data (`CandidateOut.reasoning_trail`
in `app/schemas/case.py`), not just logged — a later UI layer can render it
directly.

### 4. API endpoints (`app/main.py`)

- `POST /cases` — create a case from free-text `primary_condition`,
  `comorbidities`, `current_medications`.
- `GET /cases/{id}` — the case plus its last stored analysis result (`null`
  if never analyzed).
- `PATCH /cases/{id}` — `{"saved": true|false}`.
- `POST /cases/{id}/analyze` — runs the engine against whatever
  documents/approved-indications are currently in `arbitrage.db` (same
  "read layer over the existing pipeline" pattern as `/signals`), persists
  the result as the case's new "last analysis," and returns it in full
  (every candidate's reasoning trail and per-comorbidity checks included,
  not just scores).

**Non-prescriptive language, baked into field names, not left as a
frontend concern:** `CandidateOut` never says "recommended drug" — it's
`research_priority_score` (not "rank" or "recommendation"),
`known_indications` (not "proven uses"), and every candidate carries a
fixed `research_framing` string ("Potential research signal — evidence
suggests further investigation may be warranted. Not a treatment
recommendation."). Comorbidity check field names use `status` values
(`conflict_detected` / `no_conflict_detected` / `insufficient_evidence`),
not "safe"/"unsafe." The reasoning-trail text itself uses "clinical review
required" for conflicts rather than any accept/reject language. See
`app/schemas/case.py` for the full shape.

### 5. No-fabrication guarantee

Every score component traces back to real ingested rows: `evidence_strength
_score` is `scoring.py`'s existing score over real `documents` rows (real
`source_id`s — trial NCT IDs, Europe PMC paper IDs); `known_indications`
and comorbidity-check evidence are real openFDA label paragraphs, quoted
verbatim; a missing-data case always surfaces as an explicit
`insufficient_evidence` state (see §3), never silently omitted and never
defaulted to "no concern." Current-medication interactions always return an
explicit `insufficient_interaction_data_available` note (see below) rather
than being left out of the response shape.

### 6. Tests

34 new tests, all passing (see §8 for the full count):
- `tests/test_context_check.py` — the three-state comorbidity-conflict
  logic, using **real, live-verified openFDA text**: metformin's actual
  `CONTRAINDICATIONS` section (pulled 2026-08-19, quoted verbatim in the
  test file) correctly triggers `conflict_detected` for "renal impairment"
  and "metabolic acidosis" (both are genuine, real contraindications for
  metformin), correctly returns `no_conflict_detected` for an unrelated
  term ("asthma") when contraindications text exists, and correctly returns
  `insufficient_evidence` when no label text was ingested at all. Also
  covers the single-token-genericity guard reused from
  `disease_matching.py`, and the multi-label `combine_states` priority
  rule.
- `tests/test_case_store.py` — case creation with deliberately
  never-seen-before free-text condition/comorbidity/medication strings
  ("Glorbnitis Syndrome Type IX," etc.) to prove there's no hardcoded
  allowlist; blank-entry skipping; saved-flag updates; analysis-result
  overwrite-not-append semantics.
- `tests/test_case_analysis.py` — candidate filtering to the case's primary
  condition (matched and unmatched), the research-priority formula exactly
  (conflict penalty, insufficient-evidence penalty, the 0.30/0.10 caps,
  score never goes negative), and that the reasoning trail contains no
  prescriptive language.
- `tests/test_case_api.py` — all four endpoints, 404s for unknown case IDs,
  persistence of the last analysis result across a `GET`, and one
  real-data-shaped end-to-end test seeding a temp DB with the exact
  metformin/pancreatic-cancer signal + metformin's real contraindications
  text and confirming the API surfaces the conflict correctly through the
  full HTTP layer.

### 7. Verified end to end with real data (2026-08-19)

Re-ran openFDA ingestion for `metformin` against the live API to backfill
the new contraindications/warnings/drug_interactions fields into
`arbitrage.db` (rows ingested before this phase only have the older
fields — the migration adds the columns, but only a fresh ingest populates
them with real text). Confirmed live, via `GET https://api.fda.gov/drug/
label.json`, that metformin hydrochloride's real `CONTRAINDICATIONS`
section genuinely says: *"Severe renal impairment (eGFR below 30 mL/
min/1.73 m2)... Acute or chronic metabolic acidosis, including diabetic
ketoacidosis..."* — i.e. "renal impairment" is a real, documented
contraindication for metformin, not a made-up test case.

Created a real case through the actual running API
(`POST /cases` → `POST /cases/{id}/analyze`):

- **Primary condition:** "Pancreatic Cancer"
- **Comorbidity:** "Renal Impairment"
- **Current medication:** "Metformin 500mg" (not itself load-bearing for
  this check — v1 doesn't do medication-vs-candidate interaction checking,
  see below — included to prove case creation accepts it without special-
  casing)

Result: `metformin` was correctly surfaced as a candidate (the pre-existing
metformin/pancreatic-cancer signal, `evidence_strength_score: 0.72`, same
signal verified in Step 5's regression check). Its "renal impairment"
comorbidity check correctly came back `conflict_detected`, with evidence
text quoted verbatim from the real label: *"4 CONTRAINDICATIONS Severe
renal impairment: (eGFR below 30 mL/min/1.73 m2) (4) Metabolic acidosis,
including diabetic ketoacidosis."* — real text, not fabricated.
`research_priority_score` correctly dropped from `0.72` to `0.57`
(`0.72 - 0.15` conflict penalty, matching the documented formula exactly).
The reasoning trail rendered the full chain: known indication (type 2
diabetes) → new disease association (pancreatic cancer, via a real
ClinicalTrials.gov NCT ID) → evidence strength `0.72` → comorbidity context
check with quoted evidence and "clinical review required" → final score
`0.57`.

### 8. Test count

86 existing tests (all still passing, unmodified) + 34 new TheraLens tests
= **120 passing, 0 failing.**

### Documented limitation: current-medication drug-drug interactions (not silently skipped)

v1 explicitly does **not** attempt current-medication-vs-candidate-drug
pairwise interaction checking. Reason: unlike the comorbidity check (one
drug's label text vs. a disease term — the exact problem `diseases_match`
already solves), a real interaction check needs one drug's label to
*explicitly name the other specific drug* — a categorically harder text-
matching problem (drug names vs. drug names inside a `drug_interactions`
paragraph, with all the same brand/generic/salt-form variance
`drug_normalization.py` already has to handle for entity identity, but now
needing to happen *inside* free-text label paragraphs rather than against a
structured field). Attempting it half-heartedly risked exactly the
fabrication failure mode the brief explicitly warns against — inferring an
interaction that isn't really documented, or silently deciding "no drug
interaction field mentions it" means "safe."

Per the brief's explicit instruction, this is **not silently omitted**: the
API always returns a `current_medication_interactions` object on every
candidate, with a fixed `status: "insufficient_interaction_data_available"`
and an explanatory note
(`app/schemas/case.py`'s `CurrentMedicationInteractionNote`,
`app/core/case_analysis.py`). A caller (a later UI) can render this as a
clear "not checked yet" state rather than mistaking an empty field for "no
interactions found." If revisited in a later phase, the same
`_join_field`/token-matching pattern used for contraindications could be
extended to `drug_interactions` text specifically, but that's future work,
not something to bolt on speculatively now.

## The TheraLens frontend redesign (2026-08-19) — Phase 2

**What changed.** The frontend was rebuilt around the case workflow from
Phase 1 as the primary product experience, replacing the previous phase's
drug-list dashboard as the landing screen. The old dashboard (ticker,
opportunity cards, network graph) was kept, unmodified in logic, as one nav
destination ("Research Signals") among several, per explicit instruction —
not deleted, not the entry point.

**Navigation and structure:** a left sidebar (previously a top bar) with
Dashboard / Cases / Evidence Explorer / Drug Explorer / Research Signals,
and a persistent "+ New Case" primary CTA. A small hand-rolled hash router
(`frontend/src/router.tsx` — `useRoute`/`navigate`/`matchRoute`) replaces
the old two-tab `useState` switch; `react-router-dom` wasn't pulled in as a
new dependency because the route set is small and fixed (5 nav destinations
+ case detail/new-case), and a hash router needs no server-side route
config for a static Vite build.

**One backend addition, made for this phase:** `GET /cases` (list, newest-
first), which didn't exist after Phase 1 (only `GET /cases/{id}` did).
Dashboard's "Saved Cases" and the new Cases nav page both fundamentally
need a case list, and Phase 1 only ever exposed lookup-by-id. Implemented
as `list_cases()` in `app/ingestion/store.py` and a `CaseSummaryOut` schema
(`app/schemas/case.py`) that includes a cheap last-analysis summary
(candidate/conflict counts, top score) read straight off the already-stored
analysis JSON — no recomputation, same "read layer" pattern as every other
endpoint. Ordered by `id DESC`, not `created_at DESC`: SQLite's
`CURRENT_TIMESTAMP` default only has second resolution, so two cases
created in the same test/second would tie and sort unpredictably — `id`
(autoincrement) always reflects creation order exactly. 3 new backend tests
cover it (empty list, newest-first ordering, summary before/after analyze).
Existing 86 backend tests untouched and still passing; total backend tests
now 123.

**Dynamic disease/drug input, without a new search endpoint.** The New
Case form's condition/medication inputs (`AutocompleteInput.tsx`) suggest
from `useEntityIndex.ts`, which derives distinct drug/disease names from
whatever `/signals` currently returns — real, already-dynamic ingested
data, not a hardcoded list, and no new backend endpoint (a dedicated
search endpoint was explicitly called out as future/frontend-scope back in
Phase 1's brief). Free text is still always accepted regardless of
suggestions, matching the backend's free-text case-creation contract.

**Case results screen**, structured exactly per the brief's order: Patient
Context → Research Candidates → Safety/Context Flags → Evidence Timeline →
Evidence Graph (`pages/CaseDetail.tsx`). Each candidate card
(`components/CandidateCard.tsx`) shows evidence-strength tier
(High/Moderate/Low/Insufficient — extended `scoring.ts`'s existing tier
function with an "insufficient" band for a score of exactly 0, distinct
from "low"), the research priority score, and a worst-case context-check
badge, then expands into two side-by-side, equally-prominent panels:

- **"Why did this appear?"** — the backend's `reasoning_trail` rendered as
  an ordered list, plus real clickable source links
  (ClinicalTrials.gov/Europe PMC/openFDA) from `primary_condition_evidence`.
- **"Why might this NOT be appropriate?"** — every comorbidity check
  (conflict/no-conflict/insufficient, from the real backend three-state
  data) plus the current-medication-interaction scope note, always
  rendered (never omitted) per the "insufficient evidence, never silent"
  rule carried over from Phase 1.

A separate **Safety/Context Flags** section aggregates every detected
conflict across all candidates into one place, so a reviewer sees every
flag before drilling into any single candidate — not buried inside each
card's expandable panel.

**Case-relationship graph** (`components/CaseGraph.tsx`): patient at
center, conditions on an inner ring, candidate drugs on an outer ring,
flagged conflicts highlighted in red on both the drug node and the
connecting edge. Reuses `react-force-graph-2d` (no second graph library),
same as the existing Research Signals network view.

**Judgment call — deterministic radial layout instead of physics.** The
first implementation reused the existing `NetworkGraph`'s physics-based
force layout (charge/link forces + `zoomToFit` on a timer). For a small,
fixed hub-and-spoke shape (patient → conditions → drugs) this proved
unreliable in real-browser testing: `zoomToFit` was racing against both the
force simulation settling and `ForceGraph2D`'s own container
auto-sizing (it detects its `<canvas>` size via `ResizeObserver`, which can
report a stale/zero size on first paint) — the graph would render as a
tiny, illegibly clustered dot in the middle of the panel, and the exact
failure mode varied nondeterministically run to run. Fixed by (1)
computing node positions directly with fixed angles on two rings
(`fx`/`fy`, no force simulation needed — `cooldownTicks={0}`) since the
graph's shape is already known from the data, not something that benefits
from physics, and (2) measuring the container with our own
`ResizeObserver` and passing explicit `width`/`height` to `ForceGraph2D`
instead of relying on its internal auto-sizing timing. This degrades
gracefully by construction: drug nodes are evenly spaced around the outer
ring regardless of count (1 or 20), and same-named drugs from multiple
underlying signals are deduped into one node (conflict-flagged state is
OR'd across duplicates so a real conflict is never silently dropped by a
later, cleaner signal for the same drug overwriting it).

**Safety language.** Every case-analysis screen carries the required
disclaimer (`components/Disclaimer.tsx`) — a prominent banner at the top of
the case results screen, and a persistent compact strip in the global
footer on every page. UI copy was audited for prescriptive language:
candidate cards use "potential research signal," "evidence suggests,"
"candidate for further investigation" (the backend's own
`research_framing` string, rendered verbatim); comorbidity checks render as
"conflict detected"/"no conflict detected"/"insufficient evidence," never
"safe"/"unsafe"; flagged conflicts say "clinical review required," never an
accept/reject verdict.

**Color usage for safety meaning (per the dataviz skill).** The
safety/context status colors (`--status-good`/`--status-critical`/
`--status-neutral` in `index.css`) are a deliberately separate semantic
axis from the existing evidence-strength score tier colors
(`--accent`/`--amber`/`--low`), even though some hues are reused (green for
"good," red for "conflict") — every status use ships with an icon (✓/⚠/?)
and a text label, never color alone, so the two axes can't be confused even
where hues overlap. `scoring.ts` gained `CONFLICT_STATUS_LABEL`/
`CONFLICT_STATUS_ICON`/`CONFLICT_STATUS_CLASS`/`worstConflictState` as the
single source of truth for this mapping, used consistently across the
candidate card, safety flags panel, dashboard, cases list, and graph.

**Dashboard** (`pages/Dashboard.tsx`): Saved Cases (from `GET /cases`,
filtered `saved`), High-priority Signals (existing `/signals`, filtered to
the "high" score tier), Safety Conflicts Detected (summed `conflict_count`
across all cases' last analyses), Recent Clinical Trials (deduped, dated
`clinicaltrials`-source documents from `/signals`, newest first) — all
computed client-side from existing endpoints, no new aggregation endpoints
needed beyond the one `GET /cases` list addition above.

**Files added:** `frontend/src/router.tsx`, `frontend/src/hooks/
useEntityIndex.ts`, `frontend/src/components/{AutocompleteInput,
Disclaimer,Sidebar,CandidateCard,SafetyFlagsPanel,EvidenceTimeline,
CaseGraph}.tsx`, `frontend/src/pages/{Dashboard,CasesList,NewCase,
CaseDetail,ResearchSignals,DrugExplorer,EvidenceExplorer}.tsx`.
**Files changed:** `frontend/src/App.tsx` (now the router shell),
`frontend/src/api.ts` (Case/Analysis types + calls), `frontend/src/
scoring.ts` (insufficient tier, status-color mapping), `frontend/src/
index.css` (~900 new lines: sidebar/shell, forms, candidate cards,
reasoning panels, safety flags, timeline, graph, explorer pages — all
theme tokens reused from the existing dark palette, no new design system).
**Backend files changed for the `GET /cases` addition:**
`backend/app/ingestion/store.py`, `backend/app/schemas/case.py`,
`backend/app/main.py`; **backend tests added:** 3 new cases in
`backend/tests/test_case_api.py`.

**Verified end to end in a real browser** (Chrome via browser automation,
not just component-level): created a real case (primary condition
"pancreatic cancer," comorbidity "renal impairment," medication
"metformin") through the actual New Case form against the live backend +
`arbitrage.db`. Confirmed: the analyze flow runs automatically on
submission and lands on the case detail screen; the "Why did this appear?"
panel renders the real reasoning trail with a real ClinicalTrials.gov link
(`NCT01488552`); the "Why might this NOT be appropriate?" panel correctly
shows `conflict_detected` for "renal impairment" with the same real,
verbatim openFDA contraindication text verified in Phase 1
("...Severe renal impairment (eGFR below 30 mL/min/1.73 m2)...
Metabolic acidosis..."); the Safety/Context Flags section correctly
aggregated all 5 conflicting candidates; the Evidence Timeline showed real
dated NCT records; the Case Relationship Graph rendered patient → conditions
→ metformin with the conflict edge highlighted in red; the disclaimer
banner was visible; Dashboard's Safety Conflicts Detected count reflected
the real case. No console errors in the final state.

**Bugs found and fixed during this verification pass** (not just claimed
— actually hit while testing in the browser):
- `AutocompleteInput` didn't close its suggestion dropdown on Escape,
  which could leave it open and swallowing clicks/typing meant for a field
  underneath it — added an `onKeyDown` handler (Escape and Enter both
  close and blur).
- Two candidates sharing the same drug name (the same drug matched against
  two different real-world phrasings of the same disease) produced a
  duplicate React key in `CaseDetail.tsx`'s candidate list, which React
  logs as an error and can cause silently dropped/duplicated rows — fixed
  by keying on `${drug}-${index}` instead of `drug` alone; the analogous
  case in `CaseGraph.tsx` (same drug, two nodes) was fixed by deduping into
  one node with conflict-flags OR'd together, not just avoiding the React
  warning.
- The `reasoning_trail`'s "known indications" line can concatenate raw text
  from every ingested openFDA label for a well-documented drug (10+ full
  paragraphs for metformin) into one very long string — legible-if-real but
  unusable as a UI list item. Truncated for on-screen display only
  (`CandidateCard.tsx`'s `truncate` helper, full text still in `title=`);
  the underlying data/API response is untouched.
- The case-relationship graph's zoom/fit (see judgment call above) — this
  was the most significant issue caught, not a cosmetic one: the graph was
  silently rendering as an illegible tiny cluster in real testing despite
  looking correct in code review, only caught by actually looking at
  screenshots rather than trusting the implementation.

**Not done in this phase (per explicit instruction):** no saved-case
monitoring or new-evidence notification feature. `saved` is a plain
boolean toggle (`PATCH /cases/{id}`) with no background job, polling, or
alerting behind it yet.

## TheraLens Phase 3 (2026-08-19) — detecting new evidence for saved cases

**What this is, deliberately scoped small.** Not continuous background
monitoring — Step 7's scheduler stays deferred, same decision as every
earlier phase. Instead: saving a case now snapshots its analysis, and a
manually-triggered "Re-check for new evidence" action (button on the case
page, plus a dashboard-level "check all saved cases" action) re-runs the
existing Phase 1 analysis engine and diffs the fresh result against that
snapshot.

### 1. Snapshot-on-save

New table `case_snapshots` (`app/models/case.py`'s `CaseSnapshotRecord`) —
deliberately distinct from `case_analyses` ("last analysis"), which keeps
getting overwritten by every `/analyze` and `/recheck` call. `PATCH
/cases/{id}` now snapshots the case's current last-analysis result into
this table whenever `saved` is set to `true` (`app/main.py`'s
`update_case_endpoint`) — a fixed baseline that survives subsequent
re-analyses, so "what changed since I saved this" always has something
stable to compare against.

### 2. Re-check for new evidence

`POST /cases/{id}/recheck` (one case) and `POST /cases/recheck-all`
(every saved case — still one explicit user action, not a scheduled job)
re-run `analyze_case` against whatever's currently in `arbitrage.db`, then
diff the fresh candidates against the saved snapshot's candidates
(`app/core/evidence_diff.py`). Both also refresh the case's "last
analysis" record, so the case page reflects the freshest run either way.

**Diff logic** (`diff_candidates` in `evidence_diff.py`): a drug can
appear as more than one `CandidateOut` per analysis (one per matched
disease-text variant — see Phase 1/2's `case_analysis.py`), so comparison
happens on a per-drug aggregate: the max evidence score, the union of all
real supporting `source_id`s, and the union of comorbidities flagged
`conflict_detected`, across that drug's entries. Detects, per drug:

- **evidence tier/score changes** — reported both up *and* down (a real
  score decrease is real information too, not something to quietly drop
  just because it isn't "new evidence" in the exciting sense)
- **new supporting sources** — real `source_id`s present now but absent
  from the snapshot (never fabricated; a literal set difference over real
  trial/paper/label ids)
- **new context conflicts** — a comorbidity that is `conflict_detected` now
  but wasn't in the snapshot
- **brand-new candidates** — a drug with no entry at all in the snapshot

A drug with no detected change in any of the above is omitted from the
diff entirely, so `has_new_evidence = bool(changes)` — no threshold
tuning, no "how much change counts" judgment call to make or hide.

**Non-prescriptive language, same rules as Phase 2:** summaries read "New
research candidate detected (HIGH evidence)." / "Evidence strength
changed: MODERATE -> HIGH." / "N new supporting source(s) since last
check." / "New context conflict(s) detected: X — clinical review
required." — never "improved," never "worse," never a verdict. Backend
tier labels (`app/core/case_analysis.py`'s `evidence_tier`) mirror the
frontend's `scoreTier` thresholds exactly (same HIGH/MODERATE/LOW/
INSUFFICIENT bands, same score-of-0 "insufficient" special case) so a
diff's "MODERATE -> HIGH" always matches what the candidate card already
shows for that score.

### 3. Surfacing — case page and dashboard

- **Case page** (`frontend/src/components/EvidenceCheckPanel.tsx`): a
  "Re-check for new evidence" button, a status banner (message +
  timestamp), and an expandable "View what changed" list per candidate —
  only shown for saved cases.
- **Dashboard** (`frontend/src/pages/Dashboard.tsx`): a banner ("N saved
  cases have new evidence since last checked" / "No saved cases have new
  evidence...") with a "Check all saved cases" button that calls `POST
  /cases/recheck-all` and refreshes; the Saved Cases panel and the Cases
  list page (`CasesList.tsx`) both show a "New evidence" badge per case,
  read from `GET /cases`'s new `has_new_evidence`/`evidence_checked_at`
  fields (`app/schemas/case.py`'s `CaseSummaryOut`) — themselves read
  straight off a new `case_evidence_checks` table
  (`CaseEvidenceCheckRecord`) that stores the last check's result per
  case, so the dashboard summary doesn't need to recompute anything on
  page load; it just reflects whenever a check was last (manually) run.

### 4. Tests

17 new tests, all passing:
- `tests/test_evidence_diff.py` (9 tests) — the diff engine in isolation:
  no-change produces no diff, tier changes (both up and down), new
  sources, new conflicts, brand-new candidates, multi-signal-per-drug
  aggregation, empty inputs, and change-priority ordering (new
  candidates/conflicts sort before plain tier changes).
- `tests/test_case_api.py` (+8 tests) — snapshot-on-save, `/recheck`
  requiring a saved case with an existing snapshot (400 otherwise),
  seeded-evidence detection through the full HTTP layer (new source,
  new conflict), `/recheck-all` only touching saved cases and summarizing
  correctly, and `GET /cases`/`GET /cases/{id}` correctly surfacing the
  last check result.

**Bug caught and fixed during test-writing, not just claimed:** the first
draft of two new test helpers imported `SessionLocal` directly from
`app.models.db` instead of using the test fixture's monkeypatched
`main_module.SessionLocal` — which meant they were writing seed rows
into the **real** `backend/data/arbitrage.db` instead of the fixture's
isolated temp database. Caught immediately because the tests still ran
(the real db already had all the right tables), not because they failed —
a reminder that "the test passed" isn't sufficient evidence of test
isolation. Found via inspecting `arbitrage.db` directly (`NCT-TEST-0001`/
`0002` and `LABEL-TEST-0001`/`0002` rows were present), fixed by using
`main_module.SessionLocal()` consistently, and the accidentally-inserted
rows were deleted from the real database before moving on. Backend test
count is unaffected by this (123 -> 140 is genuinely 17 new tests, not a
net change from cleanup).

### 5. Verification against real data — what was genuinely live vs. seeded

**Genuinely live:** re-ran the actual discovery-driven ingestion pipeline
(`py scripts/run_pipeline.py`, real ClinicalTrials.gov + Europe PMC +
openFDA network calls, `ARB_MAX_RESULTS_PER_SOURCE=30`). This **did**
insert real new data: 6 new ClinicalTrials.gov documents, 8 new Europe PMC
documents (out of 81 found, 73 already known), and looked up openFDA
labels for 33 discovered drugs (0 new indications inserted — all already
cached). Re-ran `POST /cases/4/recheck` against a real saved case
(id 4: "pancreatic cancer" / comorbidity "renal impairment" / medication
"metformin," saved from Phase 2's browser testing) immediately after: it
correctly reported **"No new evidence detected since this case was
saved"** — genuinely true, because none of that real newly-ingested data
happened to be about metformin or pancreatic cancer specifically (the
discovery scan is broad/unfiltered by drug, so a short time window
touching this one case's specific candidate was always unlikely — flagged
as expected in the task brief). This *is* a real, honest verification of
the negative path: the diff engine correctly did not manufacture a change
that didn't exist, even though real new data had just been ingested
elsewhere in the database.

**Controlled/seeded, clearly labeled as such — not presented as organic
discovery:** to verify the positive ("new evidence detected") path with
data that genuinely wasn't in the Phase 2 snapshot, a single document was
manually inserted directly into `arbitrage.db` (`source_id:
"SEEDED-VERIFICATION-0001"`, later `"...-0002"` for the browser re-test —
source_ids deliberately named to make clear in any DB inspection that
they are verification artifacts, not real trial data) for the same
drug/disease pair as the saved case's existing candidate. Re-checking
then correctly reported `has_new_evidence: true`, with a `CandidateChange`
for `metformin` listing the seeded `source_id` under
`new_supporting_source_ids` and the score changing from `0.72` to `1.0`
(no tier change — stayed `HIGH`, correctly not over-reported as a tier
flip it wasn't). The same seeded-verification was repeated once through
the actual browser UI (not just the API) to confirm
`EvidenceCheckPanel`'s red banner, the "View what changed" expansion, and
the Dashboard's red banner + "New evidence" badge all render correctly
end to end — screenshots showed "Metformin: 1 new supporting source since
last check" with the real seeded id displayed. **Both seeded rows were
deleted from `arbitrage.db` immediately after verification**, and a
follow-up recheck (and a dashboard "Check all saved cases" click) was run
to confirm the case correctly reported `has_new_evidence: false` again
once the seeded data was removed — the database was left in its genuine,
unmodified state, not with fabricated rows lingering in it.

**Also genuinely live, incidentally:** while restarting the backend for
this round of browser testing, a stale `uvicorn` process left running
from the Phase 2 session was still bound to port 8000, silently serving
the pre-Phase-3 API (no `/recheck` route) underneath a freshly-started
server that failed to bind and exited. The first browser click on
"Re-check for new evidence" genuinely 404'd against that stale process —
caught via the browser console, not assumed away. Killed the stale
process, confirmed the correct one was serving the new routes via a
direct `curl`, and re-ran the browser verification from there.

### Files changed/added

**Backend:** `app/models/case.py` (+`CaseSnapshotRecord`,
+`CaseEvidenceCheckRecord`), `app/schemas/case.py` (+`CandidateChange`,
+`EvidenceCheckResult`, +`RecheckAllResult`, `CaseSummaryOut`/
`CaseWithAnalysis` gain evidence-check fields), `app/core/case_analysis.py`
(+`evidence_tier`), `app/core/evidence_diff.py` (new), `app/ingestion/
store.py` (+snapshot/evidence-check save/load functions), `app/main.py`
(+`POST /cases/{id}/recheck`, +`POST /cases/recheck-all`, snapshot-on-save
wired into the existing PATCH endpoint). **Frontend:** `src/api.ts`
(+evidence-check types/calls), `src/scoring.ts` (+backend-tier-label
bridge), `src/components/EvidenceCheckPanel.tsx` (new),
`src/pages/CaseDetail.tsx` (+panel), `src/pages/Dashboard.tsx` (+banner +
check-all action), `src/pages/CasesList.tsx` (+badge), `src/index.css`
(+~150 lines for the new panel/banner/badge styles). **Tests:**
`tests/test_evidence_diff.py` (new, 9 tests), `tests/test_case_api.py`
(+8 tests).

### Test count

123 existing tests (all still passing, unmodified) + 17 new Phase 3 tests
= **140 passing, 0 failing.**
