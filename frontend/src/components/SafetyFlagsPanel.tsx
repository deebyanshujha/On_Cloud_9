import type { CandidateOut } from "../api";

interface Props {
  candidates: CandidateOut[];
}

// Surfaced as its own section (not buried inside each candidate's expandable
// panel) so a reviewer scanning the case sees every detected conflict in one
// place before drilling into any single candidate.
export default function SafetyFlagsPanel({ candidates }: Props) {
  const flags = candidates.flatMap((c) =>
    c.comorbidity_checks
      .filter((check) => check.status === "conflict_detected")
      .map((check) => ({ drug: c.drug, ...check }))
  );

  return (
    <section className="safety-flags-panel">
      <div className="section-head">
        <h2>Safety / Context Flags</h2>
        <span className={`badge ${flags.length > 0 ? "status-critical" : "status-good"}`}>
          {flags.length > 0 ? `${flags.length} conflict${flags.length === 1 ? "" : "s"} detected` : "No conflicts detected"}
        </span>
      </div>

      {flags.length === 0 ? (
        <div className="dash-empty">
          No candidate's contraindications/warnings text matched any of this case's comorbidities.
          This does not guarantee safety — see each candidate's insufficient-evidence checks below.
        </div>
      ) : (
        <ul className="safety-flags-list">
          {flags.map((f, i) => (
            <li key={i} className="safety-flag-row">
              <span className="comorbidity-check-icon status-critical">⚠</span>
              <div className="safety-flag-body">
                <div className="safety-flag-title">
                  <strong>{f.drug}</strong> vs. comorbidity <strong>{f.comorbidity}</strong>
                </div>
                {f.evidence && (
                  <>
                    <div className="safety-flag-evidence">&ldquo;{f.evidence}&rdquo;</div>
                    <div className="safety-flag-source">Source: FDA drug label (contraindications/warnings)</div>
                  </>
                )}
                <div className="safety-flag-note">Clinical review required.</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
