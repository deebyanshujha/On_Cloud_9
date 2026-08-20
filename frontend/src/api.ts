export interface SourceLink {
  source: string;
  source_id: string;
  url: string | null;
  date: string | null;
  phase: string | null;
  evidence_type?: string | null;
}

export interface Signal {
  drug: string;
  disease: string;
  score: number;
  reasons: string[];
  approved_for: string[];
  num_independent_sources: number;
  source_breakdown: Record<string, number>;
  first_detected: string | null;
  sources: SourceLink[];
}

export interface SearchResults {
  results: Signal[];
  total: number;
  limit: number;
  offset: number;
}

// --- Clean terminology autocomplete (Phase B) -------------------------------
// Structured entity search backed by NLM's free, no-login Clinical Table
// Search Service (RxTerms for medications, "conditions" for diseases) —
// never raw openFDA label text or trial titles. See app/core/terminology.py.

export interface TerminologyEntry {
  name: string;
}

export interface TerminologySearchResult {
  results: TerminologyEntry[];
  source_unavailable: boolean;
}

export interface SourceStatus {
  status: string;
  message: string | null;
  items_ingested: number;
  checked_at: string | null;
}

export interface BackendStatus {
  signal_count: number;
  sources: Record<string, SourceStatus>;
}

export interface ScholarProfile {
  id: number;
  email: string;
  username: string;
  role: "scholar";
  created_at: string | null;
}

export interface AuthSession {
  access_token: string;
  token_type: "bearer";
  profile: ScholarProfile;
}

export interface ScholarContribution {
  id: number;
  title: string;
  summary: string;
  drug: string | null;
  disease: string | null;
  source_url: string | null;
  author_name: string;
  organization: string | null;
  created_at: string | null;
}

export interface ScholarProfileInput {
  email?: string;
  username?: string;
  full_name: string;
  organization: string;
  organization_id: string;
  phone_number: string;
  experience: string;
}

export interface ScholarContributionInput {
  title: string;
  summary: string;
  drug: string;
  disease: string;
  source_url: string;
}

// --- TheraLens Cases (Phase 2) ----------------------------------------------

export interface CaseOut {
  id: number;
  primary_condition: string;
  comorbidities: string[];
  current_medications: string[];
  saved: boolean;
  created_at: string;
}

export interface CaseSummary extends CaseOut {
  last_analyzed_at: string | null;
  candidate_count: number | null;
  conflict_count: number | null;
  top_research_priority_score: number | null;
  has_new_evidence: boolean | null;
  evidence_checked_at: string | null;
}

export type ConflictState = "conflict_detected" | "no_conflict_detected" | "insufficient_evidence";

export interface ComorbidityCheck {
  comorbidity: string;
  status: ConflictState;
  evidence: string | null;
}

export interface CurrentMedicationInteractionNote {
  status: string;
  note: string;
}

export interface CandidateOut {
  drug: string;
  disease?: string;
  research_priority_score: number;
  evidence_strength_score: number;
  known_indications: string[];
  evidence_tier: string;
  evidence_tier_reason: string;
  primary_condition_evidence: SourceLink[];
  comorbidity_checks: ComorbidityCheck[];
  current_medication_interactions: CurrentMedicationInteractionNote;
  reasoning_trail: string[];
  research_framing: string;
}

// --- Cross-case conflicts (Phase B dashboard) -------------------------------

export interface CaseConflictOut {
  case_id: number;
  primary_condition: string;
  drug: string;
  comorbidity: string;
  evidence_excerpt: string | null;
  source: string;
}

export interface AnalysisResult {
  case_id: number;
  primary_condition: string;
  analyzed_at: string;
  candidates: CandidateOut[];
  research_metadata?: ResearchMetadata;
}

export interface RejectedDrug {
  raw_name: string;
  normalized_name: string | null;
  reason: string;
  source: string | null;
}

export interface RejectedRelationship {
  drug: string | null;
  disease: string | null;
  source: string;
  source_id: string;
  evidence_type: string;
  reason: string;
}

export interface SourceAttempt {
  source: string;
  status:
    | "success"
    | "no_results"
    | "timeout"
    | "http_error"
    | "parse_error"
    | "rate_limited"
    | "not_attempted";
  results_found: number;
  queries_attempted: number;
  error: string | null;
}

export interface ResearchMetadata {
  queries: string[];
  broadened_queries: string[];
  papers_retrieved: number;
  trials_retrieved: number;
  valid_drugs: string[];
  normalized_drugs: string[];
  rejected_drugs: RejectedDrug[];
  valid_drug_disease_relationships: number;
  rejected_relationships: RejectedRelationship[];
  candidate_count: number;
  evidence_gaps: string[];
  source_counts: Record<string, number>;
  source_statuses: SourceAttempt[];
  used_local_fallback: boolean;
  local_fallback_reason: string | null;
}

// --- TheraLens: evidence re-check (Phase 3) ---------------------------------
// Manually-triggered diff of a saved case's snapshot against a fresh
// re-analysis — not continuous background monitoring (see PROGRESS.md).

export interface CandidateChange {
  drug: string;
  is_new_candidate: boolean;
  evidence_tier_before: string | null;
  evidence_tier_after: string;
  evidence_score_before: number | null;
  evidence_score_after: number;
  new_supporting_source_ids: string[];
  newly_conflicted_comorbidities: string[];
  summary: string;
}

export interface EvidenceCheckResult {
  case_id: number;
  primary_condition: string;
  snapshot_analyzed_at: string | null;
  checked_at: string;
  has_new_evidence: boolean;
  changes: CandidateChange[];
  new_papers: string[];
  new_trials: string[];
  changed_evidence: string[];
  new_candidates: string[];
  removed_invalidated_candidates: string[];
  message: string;
}

export interface RecheckAllResult {
  checked_count: number;
  cases_with_new_evidence_count: number;
  results: EvidenceCheckResult[];
}

export interface CaseWithAnalysis {
  case: CaseOut;
  last_analysis: AnalysisResult | null;
  last_evidence_check: EvidenceCheckResult | null;
}

export interface CaseCreateInput {
  primary_condition: string;
  comorbidities: string[];
  current_medications: string[];
  allow_duplicate?: boolean;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`${path} -> ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function sendJson<T>(path: string, method: "POST" | "PATCH", body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    throw new Error(`${method} ${path} -> ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function authJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Authentication request failed");
  }
  return response.json() as Promise<T>;
}

export function registerScholar(email: string, username: string, password: string): Promise<AuthSession> {
  return authJson<AuthSession>("/auth/register", { email, username, password });
}

export function loginScholar(identifier: string, password: string): Promise<AuthSession> {
  return authJson<AuthSession>("/auth/login", { identifier, password });
}

export async function fetchScholarProfile(token: string): Promise<ScholarProfile> {
  const response = await fetch(`${API_BASE}/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error("Your scholar session has expired");
  return response.json() as Promise<ScholarProfile>;
}

async function authorizedJson<T>(path: string, method: "POST" | "PATCH", token: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Scholar request failed");
  }
  return response.json() as Promise<T>;
}

export function updateScholarProfile(token: string, input: ScholarProfileInput): Promise<ScholarProfile> {
  return authorizedJson<ScholarProfile>("/auth/me", "PATCH", token, input);
}

export function createScholarContribution(token: string, input: ScholarContributionInput): Promise<ScholarContribution> {
  return authorizedJson<ScholarContribution>("/scholar/contributions", "POST", token, input);
}

export function fetchCommunityResearch(): Promise<ScholarContribution[]> {
  return getJson<ScholarContribution[]>("/community-research");
}

export function fetchSignals(): Promise<Signal[]> {
  return getJson<Signal[]>("/signals");
}

export function searchSignals(query: string, limit = 20, offset = 0): Promise<SearchResults> {
  const params = new URLSearchParams({ q: query, limit: String(limit), offset: String(offset) });
  return getJson<SearchResults>(`/search?${params.toString()}`);
}

export function fetchBackendStatus(): Promise<BackendStatus> {
  return getJson<BackendStatus>("/status");
}

export function fetchSignalsForDrug(drug: string): Promise<Signal[]> {
  return getJson<Signal[]>(`/signals/${encodeURIComponent(drug)}`);
}

export function listCases(): Promise<CaseSummary[]> {
  return getJson<CaseSummary[]>("/cases");
}

export function getCase(id: number): Promise<CaseWithAnalysis> {
  return getJson<CaseWithAnalysis>(`/cases/${id}`);
}

export function createCase(input: CaseCreateInput): Promise<CaseOut> {
  return sendJson<CaseOut>("/cases", "POST", input);
}

export function analyzeCase(id: number): Promise<AnalysisResult> {
  return sendJson<AnalysisResult>(`/cases/${id}/analyze`, "POST");
}

export function setCaseSaved(id: number, saved: boolean): Promise<CaseOut> {
  return sendJson<CaseOut>(`/cases/${id}`, "PATCH", { saved });
}

export function recheckCase(id: number): Promise<EvidenceCheckResult> {
  return sendJson<EvidenceCheckResult>(`/cases/${id}/recheck`, "POST");
}

export function recheckAllCases(): Promise<RecheckAllResult> {
  return sendJson<RecheckAllResult>("/cases/recheck-all", "POST");
}

export function getConflicts(): Promise<CaseConflictOut[]> {
  return getJson<CaseConflictOut[]>("/cases/conflicts");
}

export function searchMedications(query: string): Promise<TerminologySearchResult> {
  const params = new URLSearchParams({ q: query });
  return getJson<TerminologySearchResult>(`/medications/search?${params.toString()}`);
}

export function searchConditions(query: string): Promise<TerminologySearchResult> {
  const params = new URLSearchParams({ q: query });
  return getJson<TerminologySearchResult>(`/conditions/search?${params.toString()}`);
}
