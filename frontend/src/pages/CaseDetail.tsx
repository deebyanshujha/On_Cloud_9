import { useCallback, useEffect, useState } from "react";
import { analyzeCase, getCase, recheckCase, setCaseSaved, type CaseWithAnalysis } from "../api";
import CandidateCard from "../components/CandidateCard";
import CaseGraph from "../components/CaseGraph";
import Disclaimer from "../components/Disclaimer";
import EvidenceCheckPanel from "../components/EvidenceCheckPanel";
import EvidenceTimeline from "../components/EvidenceTimeline";
import SafetyFlagsPanel from "../components/SafetyFlagsPanel";
import { scoreTier, SCORE_TIER_LABEL } from "../scoring";

interface Props {
  caseId: number;
}

export default function CaseDetail({ caseId }: Props) {
  const [data, setData] = useState<CaseWithAnalysis | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [analyzing, setAnalyzing] = useState(false);
  const [savePending, setSavePending] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    getCase(caseId)
      .then((d) => {
        setData(d);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, [caseId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleAnalyze() {
    setAnalyzing(true);
    try {
      await analyzeCase(caseId);
      load();
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleToggleSaved() {
    if (!data) return;
    setSavePending(true);
    try {
      const updated = await setCaseSaved(caseId, !data.case.saved);
      setData({ ...data, case: updated });
    } finally {
      setSavePending(false);
    }
  }

  async function handleRecheck() {
    await recheckCase(caseId);
    load();
  }

  if (status === "loading") return <div className="page empty-state">loading case…</div>;
  if (status === "error" || !data) {
    return <div className="page empty-state">couldn't load this case — is the API running?</div>;
  }

  const { case: caseInfo, last_analysis: analysis } = data;
  const candidates = analysis?.candidates ?? [];
  const sortedCandidates = [...candidates].sort((a, b) => b.research_priority_score - a.research_priority_score);
  const bestTier = candidates.length
    ? scoreTier(Math.max(...candidates.map((c) => c.evidence_strength_score)))
    : null;

  return (
    <div className="page">
      <Disclaimer prominent />

      <div className="page-head case-detail-head">
        <div>
          <h1>{caseInfo.primary_condition}</h1>
          <p className="page-subtitle">
            Case #{caseInfo.id} · created {new Date(caseInfo.created_at).toLocaleDateString()}
          </p>
        </div>
        <div className="case-detail-actions">
          <button className="cta-button secondary" onClick={handleAnalyze} disabled={analyzing}>
            {analyzing ? "Analyzing…" : analysis ? "Re-analyze" : "Run Analysis"}
          </button>
          <button className="cta-button" onClick={handleToggleSaved} disabled={savePending}>
            {caseInfo.saved ? "★ Saved" : "☆ Save Case"}
          </button>
        </div>
      </div>

      {/* Patient Context */}
      <section className="patient-context-panel">
        <div className="section-head">
          <h2>Patient Context</h2>
        </div>
        <div className="patient-context-grid">
          <div className="patient-context-field">
            <span className="detail-section-label">Primary condition</span>
            <span className="patient-context-value">{caseInfo.primary_condition}</span>
          </div>
          <div className="patient-context-field">
            <span className="detail-section-label">Comorbidities</span>
            {caseInfo.comorbidities.length === 0 ? (
              <span className="dash-empty">none entered</span>
            ) : (
              <div className="chip-row">
                {caseInfo.comorbidities.map((c) => (
                  <span className="reason-chip" key={c}>{c}</span>
                ))}
              </div>
            )}
          </div>
          <div className="patient-context-field">
            <span className="detail-section-label">Current medications</span>
            {caseInfo.current_medications.length === 0 ? (
              <span className="dash-empty">none entered</span>
            ) : (
              <div className="chip-row">
                {caseInfo.current_medications.map((m) => (
                  <span className="reason-chip" key={m}>{m}</span>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      {caseInfo.saved && (
        <EvidenceCheckPanel lastCheck={data.last_evidence_check} onRecheck={handleRecheck} />
      )}

      {!analysis ? (
        <div className="empty-state">
          This case hasn't been analyzed yet. Click "Run Analysis" above to surface research
          candidates for it.
        </div>
      ) : (
        <>
          {/* Research Candidates */}
          <section className="research-candidates-panel">
            <div className="section-head">
              <h2>Research Candidates</h2>
              <span className="dash-panel-count mono">{sortedCandidates.length}</span>
            </div>
            {sortedCandidates.length === 0 ? (
              <div className="empty-state">
                No existing repurposing signal in the current dataset matches "{caseInfo.primary_condition}".
                As more trials/preprints/labels are ingested, candidates may appear here.
              </div>
            ) : (
              <div className="candidate-list">
                {sortedCandidates.map((c, i) => (
                  <CandidateCard key={`${c.drug}-${i}`} candidate={c} />
                ))}
              </div>
            )}
          </section>

          {/* Safety / Context Flags */}
          <SafetyFlagsPanel candidates={sortedCandidates} />

          {/* Evidence Timeline */}
          <EvidenceTimeline candidates={sortedCandidates} />

          {/* Evidence Graph */}
          <section className="evidence-graph-panel">
            <div className="section-head">
              <h2>Case Relationship Graph</h2>
              {bestTier && <span className={`badge ${bestTier}`}>{SCORE_TIER_LABEL[bestTier]} evidence present</span>}
            </div>
            {sortedCandidates.length === 0 ? (
              <div className="dash-empty">No candidates to graph yet.</div>
            ) : (
              <CaseGraph
                patientLabel="Patient"
                primaryCondition={caseInfo.primary_condition}
                comorbidities={caseInfo.comorbidities}
                candidates={sortedCandidates}
              />
            )}
          </section>
        </>
      )}
    </div>
  );
}
