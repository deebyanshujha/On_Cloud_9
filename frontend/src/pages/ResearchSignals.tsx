import { useEffect, useMemo, useState } from "react";
import { fetchSignals, type Signal } from "../api";
import NetworkGraph from "../components/NetworkGraph";
import OpportunityCard from "../components/OpportunityCard";
import SearchBar from "../components/SearchBar";
import TickerStrip from "../components/TickerStrip";

type Tab = "signals" | "network";

// This is the previous phase's dashboard (drug-list + ticker + network
// graph), repurposed unmodified as one nav destination among several rather
// than the landing experience — the case workflow is now primary. Kept
// because it's still a useful raw view over the same live, dynamic
// discovery pipeline; nothing about its logic changed.
export default function ResearchSignals() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<Tab>("signals");

  useEffect(() => {
    fetchSignals()
      .then((data) => {
        setSignals(data);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return signals;
    return signals.filter((s) => s.drug.includes(q) || s.disease.includes(q));
  }, [signals, query]);

  const topForTicker = useMemo(() => signals.slice(0, 20), [signals]);
  const drugCount = useMemo(() => new Set(signals.map((s) => s.drug)).size, [signals]);
  const diseaseCount = useMemo(() => new Set(signals.map((s) => s.disease)).size, [signals]);
  const highConfidenceCount = useMemo(() => signals.filter((s) => s.score >= 0.7).length, [signals]);

  return (
    <div className="page page-full">
      <div className="page-head research-signals-head">
        <div>
          <h1>Research Signals</h1>
          <p className="page-subtitle">
            Every drug-disease repurposing signal in the current dataset, independent of any case.
          </p>
        </div>
        <div className="tabs">
          <button className={`tab ${tab === "signals" ? "active" : ""}`} onClick={() => setTab("signals")}>
            Signals
          </button>
          <button className={`tab ${tab === "network" ? "active" : ""}`} onClick={() => setTab("network")}>
            Network
          </button>
        </div>
        <SearchBar value={query} onChange={setQuery} />
      </div>

      <TickerStrip signals={topForTicker} />

      {status === "loading" && <div className="empty-state">connecting to signal feed…</div>}
      {status === "error" && (
        <div className="empty-state">
          couldn't reach the API — is it running at <code>uvicorn app.main:app</code> on port 8000?
        </div>
      )}

      {status === "ready" && (
        <>
          <div className="summary-row">
            <div className="stat-chip">
              <span className="label">Signals</span>
              <span className="value mono">{signals.length}</span>
            </div>
            <div className="stat-chip">
              <span className="label">High conf.</span>
              <span className="value mono">{highConfidenceCount}</span>
            </div>
            <div className="stat-chip">
              <span className="label">Drugs</span>
              <span className="value mono">{drugCount}</span>
            </div>
            <div className="stat-chip">
              <span className="label">Diseases</span>
              <span className="value mono">{diseaseCount}</span>
            </div>
          </div>

          {tab === "signals" &&
            (filtered.length === 0 ? (
              <div className="empty-state">no signals match "{query}"</div>
            ) : (
              <div className="cards-grid">
                {filtered.map((s) => (
                  <OpportunityCard key={`${s.drug}-${s.disease}`} signal={s} />
                ))}
              </div>
            ))}

          {tab === "network" && <NetworkGraph signals={filtered} />}
        </>
      )}
    </div>
  );
}
