import { useEffect, useMemo, useState } from "react";
import { fetchSignals, type Signal } from "../api";
import { scoreTier, SCORE_TIER_LABEL } from "../scoring";

interface DrugSummary {
  drug: string;
  signalCount: number;
  topScore: number;
  diseases: string[];
  approvedFor: string[];
}

export default function DrugExplorer() {
  const [signals, setSignals] = useState<Signal[] | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    fetchSignals().then(setSignals).catch(() => setSignals([]));
  }, []);

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

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return drugs;
    return drugs.filter((d) => d.drug.includes(q));
  }, [drugs, query]);

  const selectedDrug = filtered.find((d) => d.drug === selected) ?? null;

  return (
    <div className="page">
      <div className="page-head">
        <h1>Drug Explorer</h1>
        <p className="page-subtitle">Every drug with at least one repurposing signal in the current dataset.</p>
      </div>

      <div className="search-wrap explorer-search">
        <div className="search-field">
          <span className="search-icon">&#9906;</span>
          <input
            className="search-input mono"
            type="text"
            placeholder="filter drugs..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>

      {signals === null ? (
        <div className="empty-state">loading…</div>
      ) : (
        <div className="explorer-layout">
          <ul className="explorer-list">
            {filtered.map((d) => (
              <li
                key={d.drug}
                className={`explorer-list-row ${selected === d.drug ? "active" : ""}`}
                onClick={() => setSelected(d.drug)}
              >
                <span className="explorer-list-title">{d.drug}</span>
                <span className={`badge ${scoreTier(d.topScore)}`}>{SCORE_TIER_LABEL[scoreTier(d.topScore)]}</span>
                <span className="mono explorer-list-count">{d.signalCount}</span>
              </li>
            ))}
          </ul>

          <div className="explorer-detail">
            {!selectedDrug ? (
              <div className="dash-empty">Select a drug to see its known indications and studied diseases.</div>
            ) : (
              <>
                <h2>{selectedDrug.drug}</h2>
                <div className="detail-section-label">Studied for ({selectedDrug.diseases.length})</div>
                <div className="chip-row">
                  {selectedDrug.diseases.map((d, i) => (
                    <span className="reason-chip" key={i}>{d}</span>
                  ))}
                </div>
                {selectedDrug.approvedFor.length > 0 && (
                  <>
                    <div className="detail-section-label">Already approved for</div>
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
