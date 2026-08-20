import { useEffect, useMemo, useState } from "react";
import { fetchSignals, searchSignals, type Signal } from "../api";
import NetworkGraph from "../components/NetworkGraph";
import OpportunityCard from "../components/OpportunityCard";
import SearchBar from "../components/SearchBar";
import TickerStrip from "../components/TickerStrip";
import { scoreTier, SOURCE_LABELS, type ScoreTier } from "../scoring";

type Tab = "signals" | "network";

const SEARCH_PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 300;
const TIER_OPTIONS: ScoreTier[] = ["high", "medium", "low"];
const SOURCE_OPTIONS = ["clinicaltrials", "biorxiv", "medrxiv"];

// Research Radar: "what is new and worth looking at?" — bounded/ranked
// search (previous phase's work, kept as-is) plus filters so browsing the
// full dataset doesn't mean scrolling an unbroken wall of cards either.
export default function ResearchSignals() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<Tab>("signals");
  const [tierFilter, setTierFilter] = useState<ScoreTier | "all">("all");
  const [sourceFilter, setSourceFilter] = useState<string>("all");

  const [searchResults, setSearchResults] = useState<Signal[]>([]);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searchStatus, setSearchStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");

  useEffect(() => {
    fetchSignals()
      .then((data) => {
        setSignals(data);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setSearchStatus("idle");
      setSearchResults([]);
      setSearchTotal(0);
      return;
    }

    setSearchStatus("loading");
    const timer = window.setTimeout(() => {
      searchSignals(q, SEARCH_PAGE_SIZE, 0)
        .then((data) => {
          setSearchResults(data.results);
          setSearchTotal(data.total);
          setSearchStatus("ready");
        })
        .catch(() => setSearchStatus("error"));
    }, SEARCH_DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [query]);

  function loadMoreSearchResults() {
    const q = query.trim();
    if (!q) return;
    searchSignals(q, SEARCH_PAGE_SIZE, searchResults.length)
      .then((data) => {
        setSearchResults((prev) => [...prev, ...data.results]);
        setSearchTotal(data.total);
      })
      .catch(() => setSearchStatus("error"));
  }

  const isSearching = query.trim().length > 0;
  const base = isSearching ? searchResults : signals;

  const filtered = useMemo(() => {
    return base.filter((s) => {
      if (tierFilter !== "all" && scoreTier(s.score) !== tierFilter) return false;
      if (sourceFilter !== "all" && !(sourceFilter in s.source_breakdown)) return false;
      return true;
    });
  }, [base, tierFilter, sourceFilter]);

  const filtersActive = tierFilter !== "all" || sourceFilter !== "all";

  const topForTicker = useMemo(() => signals.slice(0, 20), [signals]);
  const drugCount = useMemo(() => new Set(signals.map((s) => s.drug)).size, [signals]);
  const diseaseCount = useMemo(() => new Set(signals.map((s) => s.disease)).size, [signals]);
  const highConfidenceCount = useMemo(() => signals.filter((s) => s.score >= 0.7).length, [signals]);

  return (
    <div className="page page-full">
      <div className="page-head research-signals-head">
        <div>
          <h1>Research Radar</h1>
          <p className="page-subtitle">What's new and worth investigating in the current dataset.</p>
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

          {tab === "signals" && (
            <div className="explorer-filters radar-filters">
              <label className="filter-field">
                Evidence
                <select
                  className="form-input mono"
                  value={tierFilter}
                  onChange={(e) => setTierFilter(e.target.value as ScoreTier | "all")}
                >
                  <option value="all">All</option>
                  {TIER_OPTIONS.map((t) => (
                    <option key={t} value={t}>
                      {t === "high" ? "High" : t === "medium" ? "Moderate" : "Low"}
                    </option>
                  ))}
                </select>
              </label>
              <label className="filter-field">
                Source
                <select
                  className="form-input mono"
                  value={sourceFilter}
                  onChange={(e) => setSourceFilter(e.target.value)}
                >
                  <option value="all">All</option>
                  {SOURCE_OPTIONS.map((s) => (
                    <option key={s} value={s}>
                      {SOURCE_LABELS[s] ?? s}
                    </option>
                  ))}
                </select>
              </label>
              {filtersActive && (
                <button
                  className="tab"
                  onClick={() => {
                    setTierFilter("all");
                    setSourceFilter("all");
                  }}
                >
                  Clear filters
                </button>
              )}
            </div>
          )}

          {tab === "signals" && isSearching && searchStatus === "loading" && searchResults.length === 0 && (
            <div className="empty-state">searching…</div>
          )}
          {tab === "signals" && isSearching && searchStatus === "error" && (
            <div className="empty-state">search failed — try again</div>
          )}

          {tab === "signals" &&
            (!(isSearching && searchStatus === "loading" && searchResults.length === 0) &&
              searchStatus !== "error") &&
            (filtered.length === 0 ? (
              <div className="empty-state">
                {filtersActive
                  ? "no signals match this filter"
                  : `no signals match "${query}"`}
              </div>
            ) : (
              <>
                <div className="cards-grid">
                  {filtered.map((s) => (
                    <OpportunityCard key={`${s.drug}-${s.disease}`} signal={s} />
                  ))}
                </div>
                {!filtersActive && isSearching && searchTotal > searchResults.length && (
                  <div className="load-more-row">
                    <button className="tab" onClick={loadMoreSearchResults}>
                      Load more ({searchResults.length} of {searchTotal})
                    </button>
                  </div>
                )}
              </>
            ))}

          {tab === "network" && <NetworkGraph signals={filtered} />}
        </>
      )}
    </div>
  );
}
