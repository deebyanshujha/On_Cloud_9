import { useEffect, useState } from "react";
import { fetchSignals, type Signal } from "../api";

export interface EntityIndex {
  drugs: string[];
  diseases: string[];
  status: "loading" | "ready" | "error";
}

// Backs the "dynamic search, no hardcoded disease/drug list" requirement
// for the New Case form's inputs. A dedicated /diseases or /drugs search
// endpoint is out of scope for this phase (same call made in Phase 1's
// backend brief) — instead, suggestions are derived from whatever the
// existing, already-dynamic /signals endpoint currently returns. This is
// real ingested data (ClinicalTrials.gov/openFDA/Europe PMC), not a fixture,
// so the list grows/shrinks with whatever's actually in the database.
let cache: Signal[] | null = null;

export function useEntityIndex(): EntityIndex {
  const [signals, setSignals] = useState<Signal[] | null>(cache);
  const [status, setStatus] = useState<EntityIndex["status"]>(cache ? "ready" : "loading");

  useEffect(() => {
    if (cache) return;
    fetchSignals()
      .then((data) => {
        cache = data;
        setSignals(data);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, []);

  if (!signals) {
    return { drugs: [], diseases: [], status };
  }

  const drugs = new Set<string>();
  const diseases = new Set<string>();
  for (const s of signals) {
    drugs.add(s.drug);
    diseases.add(s.disease);
    for (const a of s.approved_for) diseases.add(a);
  }

  return { drugs: [...drugs].sort(), diseases: [...diseases].sort(), status };
}
