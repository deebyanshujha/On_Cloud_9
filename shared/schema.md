# Shared Data Schema

This is the common shape that every data source gets normalized into before it
reaches the comparison engine. Both the Python backend and (eventually) the
React frontend agree on these shapes so nothing gets lost in translation.

## Document (a single observed drug-disease mention)

```jsonc
{
  "drug": "metformin",           // normalized, lowercase, generic name
  "disease": "pancreatic cancer",// normalized, lowercase
  "source": "clinicaltrials",    // "clinicaltrials" | "biorxiv" | "medrxiv" | "manual"
  "source_id": "NCT01204073",    // NCT id, DOI, or manual id — used for de-duping
  "phase": "phase 2",            // trial phase if known, else null
  "date": "2024-03-01",          // ISO date the document was published/registered
  "url": "https://clinicaltrials.gov/study/NCT01204073",
  "num_mentions": 1              // how many independent documents support this pair
}
```

## ApprovedIndication (ground truth, one row per drug-disease the drug is
already FDA-approved for)

```jsonc
{
  "drug": "metformin",
  "disease": "type 2 diabetes",
  "source": "openfda",           // "openfda" | "manual"
  "source_id": "8c26dc1a-...",   // openFDA label id — used for de-duping, null for manual entries
  "url": "https://api.fda.gov/..."
}
```

Note: openFDA's `indications_and_usage` field is a free-text paragraph, not a
clean list of disease names — Step 4 ingestion stores that paragraph as-is in
`disease` (one row per label). Splitting/normalizing it into comparable
disease names is deferred to the comparison step, same as the Document
disease-name matching issue.

## Signal (output of the comparison + scoring engine)

```jsonc
{
  "drug": "metformin",
  "disease": "pancreatic cancer",
  "score": 0.71,
  "reasons": ["phase 2 trial", "2 independent mentions", "recent (2024)"],
  "supporting_documents": [ /* list of Document */ ],
  "approved_for": ["type 2 diabetes"]  // what it IS approved for, for context
}
```

Every ingestion script (ClinicalTrials.gov, bioRxiv, etc.) only has one job:
turn whatever weird format the source uses into a list of `Document` objects.
Everything downstream (comparison, scoring, storage, API) only ever talks to
these three shapes.
