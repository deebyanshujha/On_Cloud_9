import { useEffect, useMemo, useState } from "react";
import { fetchSignals, type Signal } from "../api";
import { SOURCE_LABELS } from "../scoring";

interface EvidenceRow {
  drug: string;
  disease: string;
  source: string;
  source_id: string;
  url: string | null;
  date: string | null;
  phase: string | null;
}

const SOURCE_FILTERS = ["all", "clinicaltrials", "biorxiv", "medrxiv"] as const;

export default function EvidenceExplorer() {
  const [signals, setSignals] = useState<Signal[] | null>(null);
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<(typeof SOURCE_FILTERS)[number]>("all");

  useEffect(() => {
    fetchSignals().then(setSignals).catch(() => setSignals([]));
  }, []);

  const rows = useMemo<EvidenceRow[]>(() => {
    if (!signals) return [];
    const out: EvidenceRow[] = [];
    for (const s of signals) {
      for (const src of s.sources) {
        out.push({ drug: s.drug, disease: s.disease, ...src });
      }
    }
    return out.sort((a, b) => (b.date ?? "").localeCompare(a.date ?? ""));
  }, [signals]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => {
      if (sourceFilter !== "all" && r.source !== sourceFilter) return false;
      if (!q) return true;
      return (
        r.drug.includes(q) ||
        r.disease.includes(q) ||
        r.source_id.toLowerCase().includes(q)
      );
    });
  }, [rows, query, sourceFilter]);

  return (
    <div className="page page-full">
      <div className="page-head">
        <h1>Evidence Explorer</h1>
        <p className="page-subtitle">Every underlying document (trial, preprint, label) behind the research signals.</p>
      </div>

      <div className="explorer-filters">
        <div className="search-wrap explorer-search">
          <div className="search-field">
            <span className="search-icon">&#9906;</span>
            <input
              className="search-input mono"
              type="text"
              placeholder="filter by drug, disease, or id..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        </div>
        <div className="tabs">
          {SOURCE_FILTERS.map((f) => (
            <button key={f} className={`tab ${sourceFilter === f ? "active" : ""}`} onClick={() => setSourceFilter(f)}>
              {f === "all" ? "All" : SOURCE_LABELS[f] ?? f}
            </button>
          ))}
        </div>
      </div>

      {signals === null ? (
        <div className="empty-state">loading…</div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">no evidence matches this filter</div>
      ) : (
        <div className="evidence-table-wrap">
          <table className="evidence-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Drug &rarr; Disease</th>
                <th>ID</th>
                <th>Phase</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 300).map((r, i) => (
                <tr key={`${r.source_id}-${i}`}>
                  <td>
                    <span className={`source-tag ${r.source}`}>{SOURCE_LABELS[r.source] ?? r.source}</span>
                  </td>
                  <td>
                    {r.drug} <span className="dash-row-arrow">&rarr;</span> {r.disease}
                  </td>
                  <td>
                    <a className="mono" href={r.url ?? undefined} target="_blank" rel="noreferrer">
                      {r.source_id}
                    </a>
                  </td>
                  <td className="mono">{r.phase ?? "—"}</td>
                  <td className="mono">{r.date ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length > 300 && (
            <div className="dash-empty">showing first 300 of {filtered.length} matches — refine the filter to narrow further</div>
          )}
        </div>
      )}
    </div>
  );
}
