import type { ConflictState } from "./api";

export type ScoreTier = "high" | "medium" | "low" | "insufficient";

// Score buckets are a display-only judgment call for this dashboard, not a
// change to the backend's scoring model (app/core/scoring.py) — see
// PROGRESS.md. A score of exactly 0 means run_comparison found nothing to
// distinguish this pairing (no phase/recency/mention signal at all) — shown
// as "insufficient" rather than lumped into "low" so it reads as "we don't
// really have evidence" rather than "weak evidence."
export function scoreTier(score: number): ScoreTier {
  if (score <= 0) return "insufficient";
  if (score >= 0.7) return "high";
  if (score >= 0.4) return "medium";
  return "low";
}

export const SCORE_TIER_LABEL: Record<ScoreTier, string> = {
  high: "High",
  medium: "Moderate",
  low: "Low",
  insufficient: "Insufficient",
};

export const SOURCE_LABELS: Record<string, string> = {
  clinicaltrials: "Trial",
  biorxiv: "bioRxiv",
  medrxiv: "medRxiv",
  manual: "Manual",
};

// --- Safety/context status colors -------------------------------------------
// Deliberately a SEPARATE semantic axis from evidence-strength tiers above —
// this carries real safety meaning (does this candidate's label text flag a
// conflict with the patient's comorbidity?), not a ranking. Per the dataviz
// skill's status-color guidance: reserved hues, always shipped with an
// icon + text label, never color alone.
export const CONFLICT_STATUS_LABEL: Record<ConflictState, string> = {
  conflict_detected: "Conflict detected",
  no_conflict_detected: "No conflict detected",
  insufficient_evidence: "Insufficient evidence",
};

export const CONFLICT_STATUS_ICON: Record<ConflictState, string> = {
  conflict_detected: "⚠", // ⚠
  no_conflict_detected: "✓", // ✓
  insufficient_evidence: "?",
};

export const CONFLICT_STATUS_CLASS: Record<ConflictState, string> = {
  conflict_detected: "status-critical",
  no_conflict_detected: "status-good",
  insufficient_evidence: "status-neutral",
};

// Worst-first priority for summarizing many comorbidity checks into one
// badge on a candidate card — a real conflict always outranks "insufficient
// data," which always outranks a clean check.
const STATUS_PRIORITY: Record<ConflictState, number> = {
  conflict_detected: 2,
  insufficient_evidence: 1,
  no_conflict_detected: 0,
};

export function worstConflictState(states: ConflictState[]): ConflictState | null {
  if (states.length === 0) return null;
  return states.reduce((worst, s) =>
    STATUS_PRIORITY[s] > STATUS_PRIORITY[worst] ? s : worst
  );
}

// --- Phase 3: evidence-check tier formatting --------------------------------
// The backend's evidence_tier() (app/core/case_analysis.py) uses "moderate"
// where this frontend's ScoreTier uses "medium" for the same badge/color
// class — this bridges the two so a recheck diff's tier-change badges reuse
// the exact same .badge.{tier} CSS as every other evidence-strength badge.
export function backendTierToScoreTier(tier: string | null): ScoreTier {
  if (tier === "moderate") return "medium";
  if (tier === "high" || tier === "low" || tier === "insufficient") return tier;
  return "insufficient";
}

export function tierLabelUpper(tier: string | null): string {
  return tier ? tier.toUpperCase() : "NONE";
}
