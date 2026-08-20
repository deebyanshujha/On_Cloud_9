import { useState } from "react";
import type { Signal } from "../api";
import { scoreTier, SOURCE_LABELS } from "../scoring";
import { SignalScoreBreakdown } from "./ScoreBreakdown";

interface Props {
  signal: Signal;
}

const SOURCE_ORDER = ["clinicaltrials", "biorxiv", "medrxiv"];

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "…";
}

export default function OpportunityCard({ signal }: Props) {
  const [open, setOpen] = useState(false);
  const tier = scoreTier(signal.score);
  const total =
    Object.values(signal.source_breakdown).reduce((a, b) => a + b, 0) || 1;

  return (
    <div className="card">
      <div className="card-head" onClick={() => setOpen((v) => !v)}>
        <div className="card-pair">
          <span className="drug">{signal.drug}</span>
          <span className="arrow">&rarr;</span>
          <span className="disease">{signal.disease}</span>
        </div>

        {signal.reasons.length > 0 && (
          <div className="card-why">{signal.reasons.slice(0, 2).join(" · ")}</div>
        )}

        <div className="card-metrics">
          <div className="score-block">
            <span className={`score-value mono ${tier}`}>
              {signal.score.toFixed(3)}
            </span>
            <span className={`badge ${tier}`}>
              {tier === "high" ? "High" : tier === "medium" ? "Med" : "Low"}
            </span>
          </div>
          <div className="volume-block">
            <span className="volume-value mono">
              {signal.num_independent_sources}
            </span>
            <span className="volume-label">sources</span>
          </div>
        </div>

        <div className="source-breakdown">
          <div className="source-bar">
            {SOURCE_ORDER.filter((s) => signal.source_breakdown[s]).map((s) => (
              <div
                key={s}
                className={`source-bar-seg ${s}`}
                style={{
                  width: `${((signal.source_breakdown[s] ?? 0) / total) * 100}%`,
                }}
              />
            ))}
          </div>
        </div>
        <div className="source-legend">
          {SOURCE_ORDER.filter((s) => signal.source_breakdown[s]).map((s) => (
            <span className="source-legend-item" key={s}>
              <span className={`legend-dot ${s}`} />
              {SOURCE_LABELS[s] ?? s} &times;{signal.source_breakdown[s]}
            </span>
          ))}
        </div>
      </div>

      <div className="card-footer" onClick={() => setOpen((v) => !v)}>
        <span className="first-detected mono">
          {signal.first_detected ? `first seen ${signal.first_detected}` : "date unknown"}
        </span>
        <span className="expand-hint">
          {open ? "hide" : "details"}{" "}
          <span className={`chevron ${open ? "open" : ""}`}>&#9660;</span>
        </span>
      </div>

      {open && (
        <div className="card-detail">
          <div>
            <div className="detail-section-label">Why it's flagged</div>
            <SignalScoreBreakdown signal={signal} />
            <div className="reasons-list">
              {signal.reasons.map((r, i) => (
                <span className="reason-chip" key={i}>
                  {r}
                </span>
              ))}
            </div>
          </div>

          {signal.approved_for.length > 0 && (
            <div>
              <div className="detail-section-label">
                {signal.drug} is already approved for
              </div>
              <div className="approved-text">
                {truncate(signal.approved_for.join(" / "), 260)}
              </div>
            </div>
          )}

          <div>
            <div className="detail-section-label">
              Supporting documents ({signal.sources.length})
            </div>
            <div className="sources-list">
              {signal.sources.map((src, i) => (
                <a
                  className="source-row"
                  key={`${src.source_id}-${i}`}
                  href={src.url ?? undefined}
                  target="_blank"
                  rel="noreferrer"
                >
                  <span className={`source-tag ${src.source}`}>
                    {SOURCE_LABELS[src.source] ?? src.source}
                  </span>
                  <span className="source-row-id mono">{src.source_id}</span>
                  <span className="source-row-meta">
                    {src.phase ? `${src.phase} · ` : ""}
                    {src.date ?? "n/a"}
                  </span>
                </a>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
