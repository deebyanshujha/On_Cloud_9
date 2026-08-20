import DnaHelix from "../components/DnaHelix";
import { navigate } from "../router";

const capabilities = [
  ["01", "Evidence mining", "Clinical trials, preprints, and labels normalized into traceable research evidence."],
  ["02", "Context analysis", "Case-specific candidates with FDA label checks for comorbidity conflicts."],
  ["03", "New evidence", "Saved snapshots make changes in sources, tiers, and conflicts visible over time."],
];

export default function LandingPage() {
  return (
    <div className="landing-page">
      <header className="landing-header">
        <button className="landing-brand" onClick={() => navigate("/landing")} aria-label="MedBridge home">
          <span className="landing-brand-mark">MB</span>
          <span>
            <strong>MedBridge</strong>
            <small>Biomedical research intelligence</small>
          </span>
        </button>
        <div className="landing-header-actions">
          <span className="landing-status"><i /> pipeline available</span>
          <button className="landing-text-button" onClick={() => navigate("/")}>Open platform <span>↗</span></button>
        </div>
      </header>

      <main>
        <section className="landing-hero">
          <div className="landing-hero-copy">
            <p className="eyebrow">A research console for repurposing intelligence</p>
            <h1>Find the signal<br /><em>before the label.</em></h1>
            <p className="landing-lede">
              MedBridge connects public trial, preprint, and FDA label evidence into a quiet, explainable workspace for researchers investigating new drug-disease associations.
            </p>
            <div className="landing-actions">
              <button className="landing-primary-button" onClick={() => navigate("/")}>Enter research console <span>→</span></button>
              <span className="landing-action-note">No treatment recommendations.<br />Every signal traces to source evidence.</span>
            </div>
          </div>
          <div className="landing-visual-panel">
            <div className="landing-visual-meta"><span>LIVE STRUCTURE / 034 PAIRS</span><span>DRAG LEFT / RIGHT TO ROTATE</span></div>
            <DnaHelix />
            <div className="landing-visual-caption"><span>01</span><p>Evidence is a structure, not a score alone.</p></div>
          </div>
        </section>

        <section className="landing-capabilities">
          <div className="landing-section-label"><span>What the console maps</span><span>MEDBRIDGE / 2026</span></div>
          <div className="capability-grid">
            {capabilities.map(([number, title, body]) => (
              <article key={number} className="capability-item">
                <span className="capability-number">{number}</span>
                <div><h2>{title}</h2><p>{body}</p></div>
              </article>
            ))}
          </div>
        </section>

        <section className="landing-proof">
          <div><span className="eyebrow">System note</span><h2>Deterministic by design.</h2></div>
          <p>Local biomedical NER. Public no-login sources. Hand-tuned scoring. Verbatim FDA excerpts when context conflicts are detected.</p>
          <button className="landing-outline-button" onClick={() => navigate("/signals")}>Browse current signals <span>→</span></button>
        </section>
      </main>

      <footer className="landing-footer"><span>MEDBRIDGE / CLINICAL INTELLIGENCE</span><span>Research prioritization heuristic · not a treatment recommendation</span></footer>
    </div>
  );
}
