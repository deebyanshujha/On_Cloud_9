import { useEffect, useMemo, useState } from "react";
import { fetchSignals, type Signal } from "./api";
import TickerStrip from "./components/TickerStrip";
import SearchBar from "./components/SearchBar";
import OpportunityCard from "./components/OpportunityCard";
import NetworkGraph from "./components/NetworkGraph";

type Tab = "signals" | "network";

export default function App() {
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
    return signals.filter(
      (s) => s.drug.includes(q) || s.disease.includes(q)
    );
  }, [signals, query]);

  const topForTicker = useMemo(() => signals.slice(0, 20), [signals]);

  const drugCount = useMemo(
    () => new Set(signals.map((s) => s.drug)).size,
    [signals]
  );
  const diseaseCount = useMemo(
    () => new Set(signals.map((s) => s.disease)).size,
    [signals]
  );
  const highConfidenceCount = useMemo(
    () => signals.filter((s) => s.score >= 0.7).length,
    [signals]
  );

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="bracket">[</span>ARBITR/GE<span className="bracket">]</span>
        </div>
        <span className="brand-sub">biotech repurposing signals</span>
        <div className="tabs">
          <button
            className={`tab ${tab === "signals" ? "active" : ""}`}
            onClick={() => setTab("signals")}
          >
            Signals
          </button>
          <button
            className={`tab ${tab === "network" ? "active" : ""}`}
            onClick={() => setTab("network")}
          >
            Network
          </button>
        </div>
        <SearchBar value={query} onChange={setQuery} />
      </header>

      <TickerStrip signals={topForTicker} />

      <main className="main">
        {status === "loading" && (
          <div className="empty-state">connecting to signal feed…</div>
        )}
        {status === "error" && (
          <div className="empty-state">
            couldn't reach the API — is it running at{" "}
            <code>uvicorn app.main:app</code> on port 8000?
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
      </main>

      <footer className="footer">
        <span>data: ClinicalTrials.gov · openFDA · Europe PMC (bioRxiv/medRxiv)</span>
        <span>no LLM APIs used — scoring is deterministic, NER is local</span>
      </footer>
    </div>
  );
}
