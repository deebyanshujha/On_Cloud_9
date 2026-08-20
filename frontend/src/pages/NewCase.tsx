import { useCallback, useState } from "react";
import { analyzeCase, createCase, searchConditions, searchMedications } from "../api";
import AutocompleteInput from "../components/AutocompleteInput";
import { navigate } from "../router";

async function conditionOptions(query: string): Promise<string[]> {
  const res = await searchConditions(query);
  return res.results.map((r) => r.name);
}

async function medicationOptions(query: string): Promise<string[]> {
  const res = await searchMedications(query);
  return res.results.map((r) => r.name);
}

export default function NewCase() {
  const [primaryCondition, setPrimaryCondition] = useState("");
  const [comorbidities, setComorbidities] = useState<string[]>([""]);
  const [medications, setMedications] = useState<string[]>([""]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const updateAt = (arr: string[], i: number, value: string) => {
    const next = [...arr];
    next[i] = value;
    return next;
  };

  const fetchConditions = useCallback(conditionOptions, []);
  const fetchMedications = useCallback(medicationOptions, []);

  async function handleSubmit() {
    if (!primaryCondition.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createCase({
        primary_condition: primaryCondition.trim(),
        comorbidities: comorbidities.map((c) => c.trim()).filter(Boolean),
        current_medications: medications.map((m) => m.trim()).filter(Boolean),
      });
      await analyzeCase(created.id);
      navigate(`/cases/${created.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong creating the case.");
      setSubmitting(false);
    }
  }

  return (
    <div className="page page-narrow">
      <div className="page-head">
        <h1>New Case</h1>
        <p className="page-subtitle">
          Enter a clinical context. The system will surface repurposing research signals relevant
          to it — not a diagnosis or treatment recommendation.
        </p>
      </div>

      <div className="case-form">
        <label className="form-label">
          Primary condition
          <AutocompleteInput
            value={primaryCondition}
            onChange={setPrimaryCondition}
            fetchOptions={fetchConditions}
            placeholder="e.g. pancreatic cancer"
            autoFocus
          />
        </label>

        <div className="form-section">
          <div className="form-section-label">Comorbidities</div>
          {comorbidities.map((value, i) => (
            <div className="form-row" key={i}>
              <AutocompleteInput
                value={value}
                onChange={(v) => setComorbidities(updateAt(comorbidities, i, v))}
                fetchOptions={fetchConditions}
                placeholder="e.g. renal impairment"
              />
              {comorbidities.length > 1 && (
                <button
                  type="button"
                  className="form-remove"
                  onClick={() => setComorbidities(comorbidities.filter((_, idx) => idx !== i))}
                  aria-label="Remove condition"
                >
                  &times;
                </button>
              )}
            </div>
          ))}
          <button type="button" className="form-add" onClick={() => setComorbidities([...comorbidities, ""])}>
            + Add condition
          </button>
        </div>

        <div className="form-section">
          <div className="form-section-label">Current medications</div>
          {medications.map((value, i) => (
            <div className="form-row" key={i}>
              <AutocompleteInput
                value={value}
                onChange={(v) => setMedications(updateAt(medications, i, v))}
                fetchOptions={fetchMedications}
                placeholder="e.g. metformin"
              />
              {medications.length > 1 && (
                <button
                  type="button"
                  className="form-remove"
                  onClick={() => setMedications(medications.filter((_, idx) => idx !== i))}
                  aria-label="Remove medication"
                >
                  &times;
                </button>
              )}
            </div>
          ))}
          <button type="button" className="form-add" onClick={() => setMedications([...medications, ""])}>
            + Add medication
          </button>
        </div>

        <p className="form-note">
          Current-medication interaction checking is not yet available (see the Evidence panel on
          results — this is reported explicitly, not silently skipped).
        </p>

        {error && <div className="form-error">{error}</div>}

        <button
          type="button"
          className="cta-button cta-large"
          onClick={handleSubmit}
          disabled={!primaryCondition.trim() || submitting}
        >
          {submitting ? "Analyzing…" : "Analyze Case"}
        </button>
      </div>
    </div>
  );
}
