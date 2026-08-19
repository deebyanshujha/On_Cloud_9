import { useState } from "react";
import type { EvidenceCheckResult } from "../api";
import { backendTierToScoreTier, tierLabelUpper } from "../scoring";

interface Props {
  lastCheck: EvidenceCheckResult | null;
  onRecheck: () => Promise<void>;
}

// Phase 3: manually-triggered "Re-check for new evidence" — diffs the
// case's saved snapshot against a fresh re-analysis. Deliberately NOT
// continuous background monitoring (no polling here; the user clicks a
// button). See PROGRESS.md for the scope decision.
export default function EvidenceCheckPanel({ lastCheck, onRecheck }: Props) {
  const [checking, setChecking] = useState(false);
  const [expanded, setExpanded] = useState(false);

  async function handleClick() {
    setChecking(true);
    try {
      await onRecheck();
      setExpanded(true);
    } finally {
      setChecking(false);
    }
  }

  return (
    <section className="evidence-check-panel">
      <div className="section-head">
        <h2>New Evidence Check</h2>
        <button className="cta-button secondary" onClick={handleClick} disabled={checking}>
          {checking ? "Checking…" : "Re-check for new evidence"}
        </button>
      </div>

      {!lastCheck ? (
        <div className="dash-empty">
          Not checked yet. Re-checking compares this case's saved snapshot against a fresh
          analysis of whatever evidence has since been ingested.
        </div>
      ) : (
        <>
          <div
            className={`evidence-check-summary ${lastCheck.has_new_evidence ? "status-critical" : "status-good"}`}
          >
            <span className="comorbidity-check-icon">{lastCheck.has_new_evidence ? "⚠" : "✓"}</span>
            <span>{lastCheck.message}</span>
            <span className="evidence-check-timestamp mono">
              checked {new Date(lastCheck.checked_at).toLocaleString()}
            </span>
          </div>

          {lastCheck.changes.length > 0 && (
            <>
              <button className="candidate-toggle" onClick={() => setExpanded((v) => !v)}>
                {expanded ? "Hide what changed" : "View what changed"}
                <span className={`chevron ${expanded ? "open" : ""}`}>&#9660;</span>
              </button>

              {expanded && (
                <ul className="evidence-change-list">
                  {lastCheck.changes.map((change) => (
                    <li key={change.drug} className="evidence-change-row">
                      <div className="evidence-change-head">
                        <strong>{change.drug}</strong>
                        {change.is_new_candidate ? (
                          <span className="badge status-critical">New candidate</span>
                        ) : change.evidence_tier_before !== change.evidence_tier_after ? (
                          <span className="evidence-tier-change">
                            <span className={`badge ${backendTierToScoreTier(change.evidence_tier_before)}`}>
                              {tierLabelUpper(change.evidence_tier_before)}
                            </span>
                            <span className="tier-arrow">&rarr;</span>
                            <span className={`badge ${backendTierToScoreTier(change.evidence_tier_after)}`}>
                              {tierLabelUpper(change.evidence_tier_after)}
                            </span>
                          </span>
                        ) : null}
                      </div>
                      <p className="evidence-change-summary">{change.summary}</p>
                      {change.new_supporting_source_ids.length > 0 && (
                        <div className="chip-row">
                          {change.new_supporting_source_ids.map((id) => (
                            <span className="reason-chip mono" key={id}>
                              {id}
                            </span>
                          ))}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
