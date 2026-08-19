export interface SourceLink {
  source: string;
  source_id: string;
  url: string | null;
  date: string | null;
  phase: string | null;
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

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`${path} -> ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function fetchSignals(): Promise<Signal[]> {
  return getJson<Signal[]>("/signals");
}

export function searchSignals(query: string): Promise<Signal[]> {
  return getJson<Signal[]>(`/search?q=${encodeURIComponent(query)}`);
}
