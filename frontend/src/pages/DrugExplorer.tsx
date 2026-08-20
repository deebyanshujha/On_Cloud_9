import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchSignals, searchMedications, type Signal } from "../api";
import AutocompleteInput from "../components/AutocompleteInput";
import { scoreTier, SCORE_TIER_LABEL } from "../scoring";

interface DrugSummary {
  drug: string;
  signalCount: number;
  topScore: number;
  diseases: string[];
  approvedFor: string[];
}

// RxTerms suggestions look like "metFORMIN (Oral Pill)" — strip the trailing
// form/route annotation so it can be matched against our own lowercase,
// normalized drug entities (which never carry that suffix).
function baseName(rxtermsName: string): string {
  return rxtermsName.replace(/\s*\([^)]*\)\s*$/, "").trim().toLowerCase();
}

async function medicationOptions(query: string): Promise<string[]> {
  const res = await searchMedications(query);
  return res.results.map((r) => r.name);
}

export default function DrugExplorer() {
  const [signals, setSignals] = useState<Signal[] | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    fetchSignals().then(setSignals).catch(() => setSignals([]));
  }, []);

  const fetchMedications = useCallback(medicationOptions, []);

  const drugs = useMemo<DrugSummary[]>(() => {
    if (!signals) return [];
    const map = new Map<string, DrugSummary>();
    for (const s of signals) {
      const existing = map.get(s.drug);
      if (existing) {
        existing.signalCount += 1;
        existing.topScore = Math.max(existing.topScore, s.score);
        existing.diseases.push(s.disease);
        for (const a of s.approved_for) if (!existing.approvedFor.includes(a)) existing.approvedFor.push(a);
      } else {
        map.set(s.drug, {
          drug: s.drug,
          signalCount: 1,
          topScore: s.score,
          diseases: [s.disease],
          approvedFor: [...s.approved_for],
        });
      }
    }
    return [...map.values()].sort((a, b) => b.topScore - a.topScore);
  }, [signals]);

  // Real evidence we actually have, filtered against whatever the clean
  // terminology search box is currently holding — a suggestion picked from
  // /medications/search, or free-typed text either way.
  const filtered = useMemo(() => {
    const q = baseName(query.trim() || query);
    if (!q) return drugs;
    return drugs.filter((d) => d.drug.includes(q) || q.includes(d.drug));
  }, [drugs, query]);

  const selectedDrug = filtered.find((d) => d.drug === selected) ?? drugs.find((d) => d.drug === selected) ?? null;

  return (
    <div className="page">
      <div className="page-head">
        <h1>Drug Intelligence</h1>
        <p className="page-subtitle">
          Search a medication to see its known indications and the emerging research signals studied
          against it in the current dataset.
        </p>
      </div>

      <div className="explorer-search">
        <AutocompleteInput
          value={query}
          onChange={setQuery}
          fetchOptions={fetchMedications}
          placeholder="Search a drug…"
        />
      </div>

      {signals === null ? (
        <div className="empty-state">loading…</div>
      ) : (
        <div className="explorer-layout">
          <ul className="explorer-list">
            {filtered.length === 0 ? (
              <li className="dash-empty">No drug with existing evidence matches this search yet.</li>
            ) : (
              filtered.map((d) => (
                <li
                  key={d.drug}
                  className={`explorer-list-row ${selected === d.drug ? "active" : ""}`}
                  onClick={() => setSelected(d.drug)}
                >
                  <span className="explorer-list-title">{d.drug}</span>
                  <span className={`badge ${scoreTier(d.topScore)}`}>{SCORE_TIER_LABEL[scoreTier(d.topScore)]}</span>
                  <span className="mono explorer-list-count">{d.signalCount}</span>
                </li>
              ))
            )}
          </ul>

          <div className="explorer-detail">
            {!selectedDrug ? (
              <div className="dash-empty">Select a drug to see its known indications and emerging research signals.</div>
            ) : (
              <>
                <h2>{selectedDrug.drug}</h2>
                <div className="detail-section-label">Emerging research signals ({selectedDrug.diseases.length})</div>
                <div className="chip-row">
                  {selectedDrug.diseases.map((d, i) => (
                    <span className="reason-chip" key={i}>{d}</span>
                  ))}
                </div>
                {selectedDrug.approvedFor.length > 0 && (
                  <>
                    <div className="detail-section-label">Known indications (FDA label)</div>
                    <div className="approved-text">{selectedDrug.approvedFor.join(" / ")}</div>
                  </>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
