import { useEffect, useState } from "react";
import { listCases, type CaseSummary } from "../api";
import { navigate } from "../router";

export default function CasesList() {
  const [cases, setCases] = useState<CaseSummary[] | null>(null);

  useEffect(() => {
    listCases().then(setCases).catch(() => setCases([]));
  }, []);

  return (
    <div className="page">
      <div className="page-head">
        <h1>Cases</h1>
        <p className="page-subtitle">Every clinical case created so far, most recent first.</p>
        <button className="cta-button" onClick={() => navigate("/cases/new")}>
          + New Case
        </button>
      </div>

      {cases === null ? (
        <div className="empty-state">loading cases…</div>
      ) : cases.length === 0 ? (
        <div className="empty-state">
          No cases yet. Start with <button className="link-button" onClick={() => navigate("/cases/new")}>+ New Case</button>.
        </div>
      ) : (
        <div className="case-list-grid">
          {cases.map((c) => (
            <div key={c.id} className="case-summary-card" onClick={() => navigate(`/cases/${c.id}`)}>
              <div className="case-summary-head">
                <span className="case-summary-condition">{c.primary_condition}</span>
                <div className="case-summary-badges">
                  {c.has_new_evidence && <span className="badge status-critical">New evidence</span>}
                  {c.saved && <span className="badge saved-badge">Saved</span>}
                </div>
              </div>
              <div className="case-summary-meta">
                {c.comorbidities.length > 0 && (
                  <span>{c.comorbidities.length} comorbidit{c.comorbidities.length === 1 ? "y" : "ies"}</span>
                )}
                {c.current_medications.length > 0 && (
                  <span>{c.current_medications.length} medication{c.current_medications.length === 1 ? "" : "s"}</span>
                )}
              </div>
              <div className="case-summary-footer">
                {c.candidate_count === null ? (
                  <span className="dash-empty">not yet analyzed</span>
                ) : (
                  <>
                    <span className="mono">{c.candidate_count} candidates</span>
                    {(c.conflict_count ?? 0) > 0 ? (
                      <span className="status-critical mono">⚠ {c.conflict_count} conflict{c.conflict_count === 1 ? "" : "s"}</span>
                    ) : (
                      <span className="status-good mono">✓ no conflicts</span>
                    )}
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
