import { useEffect, useMemo, useState } from "react";
import { fetchSignals, listCases, recheckAllCases, type CaseSummary, type Signal } from "../api";
import { navigate } from "../router";
import { scoreTier } from "../scoring";

function relativeDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "1 day ago";
  if (days < 30) return `${days} days ago`;
  return d.toISOString().slice(0, 10);
}

export default function Dashboard() {
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [signals, setSignals] = useState<Signal[] | null>(null);
  const [checkingAll, setCheckingAll] = useState(false);

  const reloadCases = () => listCases().then(setCases).catch(() => setCases([]));

  useEffect(() => {
    reloadCases();
    fetchSignals().then(setSignals).catch(() => setSignals([]));
  }, []);

  async function handleCheckAllSaved() {
    setCheckingAll(true);
    try {
      await recheckAllCases();
      await reloadCases();
    } finally {
      setCheckingAll(false);
    }
  }

  const savedCases = useMemo(() => (cases ?? []).filter((c) => c.saved), [cases]);
  const casesWithNewEvidence = useMemo(
    () => savedCases.filter((c) => c.has_new_evidence),
    [savedCases]
  );
  const highPrioritySignals = useMemo(
    () => (signals ?? []).filter((s) => scoreTier(s.score) === "high"),
    [signals]
  );
  const totalConflicts = useMemo(
    () => (cases ?? []).reduce((sum, c) => sum + (c.conflict_count ?? 0), 0),
    [cases]
  );
  const casesWithConflicts = useMemo(
    () => (cases ?? []).filter((c) => (c.conflict_count ?? 0) > 0),
    [cases]
  );
  const recentTrials = useMemo(() => {
    const seen = new Map<string, { drug: string; disease: string; date: string; url: string | null }>();
    for (const s of signals ?? []) {
      for (const src of s.sources) {
        if (src.source !== "clinicaltrials" || !src.date) continue;
        if (!seen.has(src.source_id)) {
          seen.set(src.source_id, { drug: s.drug, disease: s.disease, date: src.date, url: src.url });
        }
      }
    }
    return [...seen.entries()]
      .sort((a, b) => (b[1].date > a[1].date ? 1 : -1))
      .slice(0, 8);
  }, [signals]);

  const loading = cases === null || signals === null;

  return (
    <div className="page">
      <div className="page-head">
        <h1>Dashboard</h1>
        <p className="page-subtitle">Your cases and the research signals behind them.</p>
      </div>

      {loading ? (
        <div className="empty-state">loading dashboard…</div>
      ) : (
        <>
          {savedCases.length > 0 && (
            <div
              className={`new-evidence-banner ${casesWithNewEvidence.length > 0 ? "status-critical" : "status-good"}`}
            >
              <span className="comorbidity-check-icon">
                {casesWithNewEvidence.length > 0 ? "⚠" : "✓"}
              </span>
              <span>
                {casesWithNewEvidence.length > 0
                  ? `${casesWithNewEvidence.length} saved case${casesWithNewEvidence.length === 1 ? "" : "s"} have new evidence since last checked.`
                  : "No saved cases have new evidence since they were last checked."}
              </span>
              <button className="cta-button secondary" onClick={handleCheckAllSaved} disabled={checkingAll}>
                {checkingAll ? "Checking…" : "Check all saved cases"}
              </button>
            </div>
          )}

        <div className="dashboard-grid">
          <section className="dash-panel">
            <div className="dash-panel-head">
              <h2>Saved Cases</h2>
              <span className="dash-panel-count mono">{savedCases.length}</span>
            </div>
            {savedCases.length === 0 ? (
              <div className="dash-empty">
                No saved cases yet. Save a case from its results screen to track it here.
              </div>
            ) : (
              <ul className="dash-list">
                {savedCases.map((c) => (
                  <li key={c.id} className="dash-list-row" onClick={() => navigate(`/cases/${c.id}`)}>
                    <span className="dash-row-title">
                      {c.primary_condition}
                      {c.has_new_evidence && <span className="badge status-critical new-evidence-badge">New evidence</span>}
                    </span>
                    <span className="dash-row-meta mono">
                      {c.candidate_count ?? 0} candidates
                      {(c.conflict_count ?? 0) > 0 && (
                        <span className="status-critical"> · {c.conflict_count} conflict{c.conflict_count === 1 ? "" : "s"}</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="dash-panel">
            <div className="dash-panel-head">
              <h2>High-priority Signals</h2>
              <span className="dash-panel-count mono">{highPrioritySignals.length}</span>
            </div>
            {highPrioritySignals.length === 0 ? (
              <div className="dash-empty">No high-confidence signals in the current dataset.</div>
            ) : (
              <ul className="dash-list">
                {highPrioritySignals.slice(0, 6).map((s) => (
                  <li key={`${s.drug}-${s.disease}`} className="dash-list-row" onClick={() => navigate("/signals")}>
                    <span className="dash-row-title">
                      {s.drug} <span className="dash-row-arrow">&rarr;</span> {s.disease}
                    </span>
                    <span className="score-value high mono dash-row-score">{s.score.toFixed(2)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="dash-panel">
            <div className="dash-panel-head">
              <h2>Safety Conflicts Detected</h2>
              <span className="dash-panel-count mono status-critical">{totalConflicts}</span>
            </div>
            {casesWithConflicts.length === 0 ? (
              <div className="dash-empty">No comorbidity conflicts detected across analyzed cases.</div>
            ) : (
              <ul className="dash-list">
                {casesWithConflicts.map((c) => (
                  <li key={c.id} className="dash-list-row" onClick={() => navigate(`/cases/${c.id}`)}>
                    <span className="dash-row-title">{c.primary_condition}</span>
                    <span className="dash-row-meta status-critical mono">
                      ⚠ {c.conflict_count} conflict{c.conflict_count === 1 ? "" : "s"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="dash-panel">
            <div className="dash-panel-head">
              <h2>Recent Clinical Trials</h2>
              <span className="dash-panel-count mono">{recentTrials.length}</span>
            </div>
            {recentTrials.length === 0 ? (
              <div className="dash-empty">No dated trial evidence in the current dataset.</div>
            ) : (
              <ul className="dash-list">
                {recentTrials.map(([id, t]) => (
                  <li key={id} className="dash-list-row">
                    <a className="dash-row-link" href={t.url ?? undefined} target="_blank" rel="noreferrer">
                      <span className="dash-row-title">
                        {t.drug} <span className="dash-row-arrow">&rarr;</span> {t.disease}
                      </span>
                      <span className="dash-row-meta mono">{relativeDate(t.date)}</span>
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
        </>
      )}
    </div>
  );
}
