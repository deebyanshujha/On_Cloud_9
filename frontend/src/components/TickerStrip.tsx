import type { Signal } from "../api";
import { scoreTier } from "../scoring";

interface Props {
  signals: Signal[];
}

export default function TickerStrip({ signals }: Props) {
  if (signals.length === 0) return null;

  // Duplicate the list so the CSS animation (translateX -50%) loops seamlessly.
  const items = [...signals, ...signals];

  return (
    <div className="ticker">
      <div className="ticker-track">
        {items.map((s, i) => (
          <span className="ticker-item" key={`${s.drug}-${s.disease}-${i}`}>
            <span className="pair">
              {s.drug} <span className="arrow">&rarr;</span> {s.disease}
            </span>
            <span className={`score mono ${scoreTier(s.score)}`}>
              {s.score.toFixed(2)}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
