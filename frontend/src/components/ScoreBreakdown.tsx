import type { CandidateOut, Signal } from "../api";
import { SOURCE_LABELS } from "../scoring";

interface SignalProps {
  signal: Signal;
}

interface CandidateProps {
  candidate: CandidateOut;
}

function dateRange(dates: Array<string | null>): string {
  const known = dates.filter((date): date is string => Boolean(date)).sort();
  if (known.length === 0) return "date unavailable";
  if (known[0] === known[known.length - 1]) return known[0];
  return `${known[0]} to ${known[known.length - 1]}`;
}

export function SignalScoreBreakdown({ signal }: SignalProps) {
  const sourceEntries = Object.entries(signal.source_breakdown);

  return (
    <details className="score-ledger">
      <summary>Score inputs</summary>
      <div className="score-ledger-grid">
        <span>strongest source</span>
        <strong>{sourceEntries.map(([source]) => SOURCE_LABELS[source] ?? source).join(", ") || "none"}</strong>
        <span>independent evidence</span>
        <strong className="mono">{signal.num_independent_sources} source IDs</strong>
        <span>evidence dates</span>
        <strong className="mono">{dateRange(signal.sources.map((source) => source.date))}</strong>
        <span>phase data</span>
        <strong>{signal.sources.some((source) => source.phase) ? "present" : "not reported"}</strong>
      </div>
      <p className="score-ledger-note">The backend score combines source strength, phase, recency, and independent mentions. Exact weights remain in the scoring engine.</p>
    </details>
  );
}

export function CandidateScoreBreakdown({ candidate }: CandidateProps) {
  const conflicts = candidate.comorbidity_checks.filter((check) => check.status === "conflict_detected").length;
  const insufficient = candidate.comorbidity_checks.filter((check) => check.status === "insufficient_evidence").length;

  return (
    <details className="score-ledger">
      <summary>Priority calculation</summary>
      <div className="score-ledger-grid">
        <span>evidence strength</span>
        <strong className="mono">{candidate.evidence_strength_score.toFixed(3)}</strong>
        <span>conflict penalty</span>
        <strong className="mono">−{Math.min(0.3, conflicts * 0.15).toFixed(2)} ({conflicts} detected)</strong>
        <span>uncertainty penalty</span>
        <strong className="mono">−{Math.min(0.1, insufficient * 0.03).toFixed(2)} ({insufficient} insufficient)</strong>
        <span>research priority</span>
        <strong className="mono score-ledger-total">{candidate.research_priority_score.toFixed(3)}</strong>
      </div>
      <p className="score-ledger-note">Penalty math is derived from the returned comorbidity states; it is a research-prioritization heuristic, not a treatment recommendation.</p>
    </details>
  );
}
