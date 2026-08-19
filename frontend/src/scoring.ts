export type ScoreTier = "high" | "medium" | "low";

// Score buckets are a display-only judgment call for this dashboard, not a
// change to the backend's scoring model (app/core/scoring.py) — see
// PROGRESS.md.
export function scoreTier(score: number): ScoreTier {
  if (score >= 0.7) return "high";
  if (score >= 0.4) return "medium";
  return "low";
}

export const SOURCE_LABELS: Record<string, string> = {
  clinicaltrials: "Trial",
  biorxiv: "bioRxiv",
  medrxiv: "medRxiv",
  manual: "Manual",
};
