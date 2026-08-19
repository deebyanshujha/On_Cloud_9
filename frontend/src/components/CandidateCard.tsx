import { useState } from "react";
import type { CandidateOut } from "../api";
import {
  CONFLICT_STATUS_CLASS,
  CONFLICT_STATUS_ICON,
  CONFLICT_STATUS_LABEL,
  SCORE_TIER_LABEL,
  SOURCE_LABELS,
  scoreTier,
  worstConflictState,
} from "../scoring";

interface Props {
  candidate: CandidateOut;
}

export default function CandidateCard({ candidate }: Props) {
  const [open, setOpen] = useState(false);
  const tier = scoreTier(candidate.evidence_strength_score);
  const worst = worstConflictState(candidate.comorbidity_checks.map((c) => c.status));

  return (
    <div className="candidate-card">
      <div className="candidate-head">
        <div className="candidate-title">
          <span className="candidate-drug">{candidate.drug}</span>
          <span className="candidate-framing">{candidate.research_framing}</span>
        </div>

        <div className="candidate-metrics">
          <div className="metric-block">
            <span className="metric-label">Evidence strength</span>
            <span className={`badge ${tier}`}>{SCORE_TIER_LABEL[tier]}</span>
          </div>
          <div className="metric-block">
            <span className="metric-label">Research priority</span>
            <span className={`score-value mono ${tier}`}>{candidate.research_priority_score.toFixed(2)}</span>
          </div>
          {worst && (
            <div className="metric-block">
              <span className="metric-label">Context check</span>
              <span className={`badge ${CONFLICT_STATUS_CLASS[worst]}`}>
                {CONFLICT_STATUS_ICON[worst]} {CONFLICT_STATUS_LABEL[worst]}
              </span>
            </div>
          )}
        </div>
      </div>

      {candidate.known_indications.length > 0 && (
        <div className="candidate-known-for">
          Already approved for other uses — this is a new, unapproved association being studied.
        </div>
      )}

      <button className="candidate-toggle" onClick={() => setOpen((v) => !v)}>
        {open ? "Hide reasoning" : "Why did this appear, and why might it not be appropriate?"}
        <span className={`chevron ${open ? "open" : ""}`}>&#9660;</span>
      </button>

      {open && (
        <div className="candidate-detail-grid">
          <WhyAppeared candidate={candidate} />
          <WhyNotAppropriate candidate={candidate} />
        </div>
      )}
    </div>
  );
}

// The backend's reasoning trail quotes raw openFDA paragraphs verbatim
// (no fabrication/re-summarizing) — a drug with many ingested labels can
// produce a single trail entry hundreds of words long. Truncated here for
// on-screen legibility only; nothing about the underlying data changes.
const TRAIL_ENTRY_MAX_CHARS = 320;

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "…";
}

function WhyAppeared({ candidate }: { candidate: CandidateOut }) {
  return (
    <div className="reasoning-panel why-appeared">
      <div className="reasoning-panel-head">
        <span className="reasoning-panel-icon status-good">✓</span>
        <h3>Why did this appear?</h3>
      </div>
      <ol className="reasoning-trail">
        {candidate.reasoning_trail.map((step, i) => (
          <li key={i} title={step.length > TRAIL_ENTRY_MAX_CHARS ? step : undefined}>
            {truncate(step, TRAIL_ENTRY_MAX_CHARS)}
          </li>
        ))}
      </ol>

      {candidate.primary_condition_evidence.length > 0 && (
        <div className="evidence-links">
          <div className="detail-section-label">Supporting sources</div>
          <div className="sources-list">
            {candidate.primary_condition_evidence.map((src, i) => (
              <a
                className="source-row"
                key={`${src.source_id}-${i}`}
                href={src.url ?? undefined}
                target="_blank"
                rel="noreferrer"
              >
                <span className={`source-tag ${src.source}`}>{SOURCE_LABELS[src.source] ?? src.source}</span>
                <span className="source-row-id mono">{src.source_id}</span>
                <span className="source-row-meta">
                  {src.phase ? `${src.phase} · ` : ""}
                  {src.date ?? "n/a"}
                </span>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function WhyNotAppropriate({ candidate }: { candidate: CandidateOut }) {
  const hasComorbidityChecks = candidate.comorbidity_checks.length > 0;

  return (
    <div className="reasoning-panel why-not">
      <div className="reasoning-panel-head">
        <span className="reasoning-panel-icon status-critical">⚠</span>
        <h3>Why might this NOT be appropriate?</h3>
      </div>

      {!hasComorbidityChecks ? (
        <div className="dash-empty">No comorbidities were entered for this case — no context checks to show.</div>
      ) : (
        <ul className="comorbidity-check-list">
          {candidate.comorbidity_checks.map((check) => (
            <li key={check.comorbidity} className={`comorbidity-check ${CONFLICT_STATUS_CLASS[check.status]}`}>
              <div className="comorbidity-check-head">
                <span className="comorbidity-check-icon">{CONFLICT_STATUS_ICON[check.status]}</span>
                <span className="comorbidity-check-name">{check.comorbidity}</span>
                <span className="comorbidity-check-status">{CONFLICT_STATUS_LABEL[check.status]}</span>
              </div>
              {check.evidence && <div className="comorbidity-check-evidence">&ldquo;{check.evidence}&rdquo;</div>}
            </li>
          ))}
        </ul>
      )}

      <div className={`interaction-note ${candidate.current_medication_interactions.status === "insufficient_interaction_data_available" ? "status-neutral" : ""}`}>
        <span className="comorbidity-check-icon">?</span>
        <span>{candidate.current_medication_interactions.note}</span>
      </div>
    </div>
  );
}
