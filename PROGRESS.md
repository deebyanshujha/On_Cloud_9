# Progress Log — Real-Time Biotech Arbitrage Engine

_Last updated: 2026-08-19 — after Step 8 (Step 7 deliberately deferred)_

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
- [ ] **Step 9 — Validation against known cases using live data.** Not started
  (Step 2 already validates the *logic* using fixture data — Step 9 repeats
  that check once real data is flowing).

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

## Next step

Checking in with the user before deciding what's next — either picking up
the deferred Step 7 (scheduler), or Step 9 (validation against known cases
using live data) per the original build order.

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
