import type { CandidateOut } from "../api";
import { SOURCE_LABELS } from "../scoring";

interface Props {
  candidates: CandidateOut[];
}

interface TimelineEntry {
  drug: string;
  source: string;
  source_id: string;
  url: string | null;
  date: string;
}

export default function EvidenceTimeline({ candidates }: Props) {
  const entries: TimelineEntry[] = candidates
    .flatMap((c) =>
      c.primary_condition_evidence
        .filter((e) => e.date)
        .map((e) => ({ drug: c.drug, source: e.source, source_id: e.source_id, url: e.url, date: e.date as string }))
    )
    .sort((a, b) => (a.date < b.date ? 1 : -1));

  return (
    <section className="evidence-timeline-panel">
      <div className="section-head">
        <h2>Evidence Timeline</h2>
        <span className="dash-panel-count mono">{entries.length}</span>
      </div>

      {entries.length === 0 ? (
        <div className="dash-empty">No dated supporting evidence for this case's candidates.</div>
      ) : (
        <ol className="timeline">
          {entries.map((e, i) => (
            <li key={`${e.source_id}-${i}`} className="timeline-entry">
              <span className="timeline-dot" />
              <div className="timeline-body">
                <div className="timeline-date mono">{e.date}</div>
                <a className="timeline-link" href={e.url ?? undefined} target="_blank" rel="noreferrer">
                  <span className={`source-tag ${e.source}`}>{SOURCE_LABELS[e.source] ?? e.source}</span>
                  <span className="timeline-title">{e.drug}</span>
                  <span className="timeline-id mono">{e.source_id}</span>
                </a>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
