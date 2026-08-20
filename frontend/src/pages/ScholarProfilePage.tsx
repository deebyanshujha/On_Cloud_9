import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "../auth";
import { navigate } from "../router";
import "../styles/ProfilePage.css";

interface ResearchEntry {
  title: string;
  summary: string;
  drug: string;
  disease: string;
  source_url: string;
  therapeutic_area: string;
  stage_of_research: string;
  collaboration_interests: string;
}

const EMPTY_RESEARCH: ResearchEntry = {
  title: "",
  summary: "",
  drug: "",
  disease: "",
  source_url: "",
  therapeutic_area: "",
  stage_of_research: "",
  collaboration_interests: "",
};

export default function ScholarProfilePage() {
  const { profile, loading, logout, updateProfile, contributeResearch } = useAuth();
  const [details, setDetails] = useState({
    full_name: "",
    organization: "",
    organization_id: "",
    phone_number: "",
    experience: "",
    title: "",
    orcid_id: "",
    linkedin_profile: "",
    research_interests: "",
  });
  const [draft, setDraft] = useState<ResearchEntry>({ ...EMPTY_RESEARCH });
  const [queue, setQueue] = useState<ResearchEntry[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [editingIndex, setEditingIndex] = useState<number | null>(null);

  // Identity-card inline edit
  const [editingIdentity, setEditingIdentity] = useState(false);
  const [identityDraft, setIdentityDraft] = useState({ username: "", email: "" });
  const [identitySaving, setIdentitySaving] = useState(false);
  const [identityError, setIdentityError] = useState("");

  // Accordion state — both collapsed by default for a clean initial view
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [contributeOpen, setContributeOpen] = useState(false);

  useEffect(() => {
    if (profile) {
      setDetails({
        full_name: profile.full_name ?? "",
        organization: profile.organization ?? "",
        organization_id: profile.organization_id ?? "",
        phone_number: profile.phone_number ?? "",
        experience: profile.experience ?? "",
        title: profile.title ?? "",
        orcid_id: profile.orcid_id ?? "",
        linkedin_profile: profile.linkedin_profile ?? "",
        research_interests: profile.research_interests ?? "",
      });
    }
  }, [profile]);

  function addToQueue(event: FormEvent) {
    event.preventDefault();
    if (!draft.title.trim() || !draft.summary.trim()) return;

    if (editingIndex !== null) {
      setQueue((prev) => prev.map((item, i) => (i === editingIndex ? { ...draft } : item)));
      setEditingIndex(null);
    } else {
      setQueue((prev) => [...prev, { ...draft }]);
    }
    setDraft({ ...EMPTY_RESEARCH });
  }

  function removeFromQueue(index: number) {
    setQueue((prev) => prev.filter((_, i) => i !== index));
    if (editingIndex === index) {
      setEditingIndex(null);
      setDraft({ ...EMPTY_RESEARCH });
    }
  }

  function editEntry(index: number) {
    setDraft({ ...queue[index] });
    setEditingIndex(index);
    setContributeOpen(true);
  }

  async function submitAll() {
    if (queue.length === 0) return;
    setSubmitting(true);
    try {
      for (const entry of queue) {
        await contributeResearch(entry);
      }
      const count = queue.length;
      setQueue([]);
      setDraft({ ...EMPTY_RESEARCH });
      setEditingIndex(null);
      setMessage(`${count} research note${count > 1 ? "s" : ""} shared with visitors.`);
    } catch {
      setMessage("Some contributions failed — please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <div className="empty-state">Loading profile…</div>;
  if (!profile)
    return (
      <section className="profile-page">
        <div className="profile-empty-auth">
          <h2>Scholar Access Required</h2>
          <p>
            Please sign in with a scholar account to view and manage your
            profile, and to contribute to the research signals database.
          </p>
          <button className="cta-button" onClick={() => navigate("/login")}>
            Sign in to Scholar Account
          </button>
        </div>
      </section>
    );

  // Quick summary line for collapsed Professional details
  const detailsSummary = [details.full_name, details.title, details.organization]
    .filter(Boolean)
    .join(" · ") || "No details added yet";

  return (
    <section className="profile-page">
      {/* ── Identity header ──────────────────────────────────────── */}
      <p className="eyebrow">Scholar Profile</p>
      <h1>{profile.username}</h1>

      <div className="profile-card">
        <span className="profile-avatar">
          {profile.username.slice(0, 1).toUpperCase()}
        </span>
        {editingIdentity ? (
          <form
            className="profile-card-edit-form"
            onSubmit={async (e) => {
              e.preventDefault();
              setIdentityError("");
              const trimmedUsername = identityDraft.username.trim().toLowerCase();
              const trimmedEmail = identityDraft.email.trim().toLowerCase();
              if (!trimmedUsername || !trimmedEmail) {
                setIdentityError("Username and email are required.");
                return;
              }
              setIdentitySaving(true);
              try {
                await updateProfile({
                  ...details,
                  username: trimmedUsername,
                  email: trimmedEmail,
                });
                setEditingIdentity(false);
                setMessage("Account details updated.");
              } catch (err: unknown) {
                setIdentityError(
                  err instanceof Error ? err.message : "Failed to update account details."
                );
              } finally {
                setIdentitySaving(false);
              }
            }}
          >
            <label>
              Username
              <input
                value={identityDraft.username}
                onChange={(e) =>
                  setIdentityDraft({ ...identityDraft, username: e.target.value })
                }
                placeholder="Your username"
                required
                minLength={3}
                maxLength={40}
                autoFocus
              />
            </label>
            <label>
              Email
              <input
                type="email"
                value={identityDraft.email}
                onChange={(e) =>
                  setIdentityDraft({ ...identityDraft, email: e.target.value })
                }
                placeholder="scholar@example.com"
                required
                minLength={5}
                maxLength={254}
              />
            </label>
            {identityError && (
              <p className="identity-edit-error">{identityError}</p>
            )}
            <div className="identity-edit-actions">
              <button
                type="submit"
                className="profile-submit"
                disabled={identitySaving}
              >
                {identitySaving ? "Saving…" : "Save changes"}
              </button>
              <button
                type="button"
                className="paper-entry-cancel"
                onClick={() => {
                  setEditingIdentity(false);
                  setIdentityError("");
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <div className="profile-card-display">
            <div>
              <strong>{profile.username}</strong>
              <span>{profile.email}</span>
              <span>Research scholar account</span>
            </div>
            <button
              type="button"
              className="profile-card-edit-btn"
              title="Edit username and email"
              onClick={() => {
                setIdentityDraft({
                  username: profile.username,
                  email: profile.email,
                });
                setIdentityError("");
                setEditingIdentity(true);
              }}
            >
              ✎
            </button>
          </div>
        )}
      </div>

      <p className="profile-note">
        Your scholar identity is separate from guest mode. These optional
        details are displayed in your scholar profile only — contact details
        are never shown in public contributions.
      </p>

      {/* ══════════════════════════════════════════════════════════════
          SECTION 1 — Professional Details (collapsible)
      ══════════════════════════════════════════════════════════════ */}
      <div className={`accordion ${detailsOpen ? "accordion--open" : ""}`}>
        <button
          type="button"
          className="accordion-trigger"
          onClick={() => setDetailsOpen(!detailsOpen)}
          aria-expanded={detailsOpen}
        >
          <div className="accordion-trigger-left">
            <h2>Professional details</h2>
            {!detailsOpen && (
              <span className="accordion-preview">{detailsSummary}</span>
            )}
          </div>
          <div className="accordion-trigger-right">
            <span className="accordion-badge">Optional</span>
            <span className={`accordion-chevron ${detailsOpen ? "accordion-chevron--open" : ""}`}>
              ▾
            </span>
          </div>
        </button>

        <div className="accordion-body">
          <div className="accordion-body-inner">
            <form
              className="profile-form"
              onSubmit={async (event: FormEvent) => {
                event.preventDefault();
                await updateProfile(details);
                setMessage("Profile saved.");
              }}
            >
              {/* Sub-group: Identity */}
              <div className="profile-fieldgroup">
                <span className="profile-group-label">Identity</span>
                <div className="form-grid">
                  <label>
                    Full name displayed
                    <input
                      value={details.full_name}
                      onChange={(e) => setDetails({ ...details, full_name: e.target.value })}
                      placeholder="Your public scholar name"
                    />
                  </label>
                  <label>
                    Title / Role
                    <input
                      value={details.title}
                      onChange={(e) => setDetails({ ...details, title: e.target.value })}
                      placeholder="e.g., Senior Researcher"
                    />
                  </label>
                </div>
                <div style={{ marginTop: "var(--space-4)" }}>
                  <label className="label-code">
                    ORCID iD
                    <input
                      value={details.orcid_id}
                      onChange={(e) => setDetails({ ...details, orcid_id: e.target.value })}
                      placeholder="0000-0000-0000-0000"
                    />
                  </label>
                </div>
              </div>

              {/* Sub-group: Organization & Contact */}
              <div className="profile-fieldgroup">
                <span className="profile-group-label">Organization &amp; Contact</span>
                <div className="form-grid">
                  <label>
                    Institution / Organization
                    <input
                      value={details.organization}
                      onChange={(e) => setDetails({ ...details, organization: e.target.value })}
                      placeholder="Optional"
                    />
                  </label>
                  <label>
                    Phone number
                    <input
                      type="tel"
                      value={details.phone_number}
                      onChange={(e) => setDetails({ ...details, phone_number: e.target.value })}
                      placeholder="Profile only — not public"
                    />
                  </label>
                </div>
                <div className="form-grid" style={{ marginTop: "var(--space-4)" }}>
                  <label className="label-code">
                    Institution ID (ROR / GRID)
                    <input
                      value={details.organization_id}
                      onChange={(e) => setDetails({ ...details, organization_id: e.target.value })}
                      placeholder="e.g., ror.org/04aj4c181"
                    />
                    <small className="profile-field-hint">
                      Optional — research registry ID for your institution
                    </small>
                  </label>
                  <label className="label-code">
                    LinkedIn Profile
                    <input
                      type="url"
                      value={details.linkedin_profile}
                      onChange={(e) => setDetails({ ...details, linkedin_profile: e.target.value })}
                      placeholder="https://linkedin.com/in/..."
                    />
                  </label>
                </div>
              </div>

              {/* Sub-group: Research Background */}
              <div className="profile-fieldgroup">
                <span className="profile-group-label">Research Background</span>
                <label>
                  Research Interests
                  <textarea
                    value={details.research_interests}
                    onChange={(e) => setDetails({ ...details, research_interests: e.target.value })}
                    placeholder="List your research interests, separated by commas"
                  />
                </label>
                <div style={{ marginTop: "var(--space-4)" }}>
                  <label>
                    Research Experience &amp; Bio
                    <textarea
                      value={details.experience}
                      onChange={(e) => setDetails({ ...details, experience: e.target.value })}
                      placeholder="Areas of work, years of experience, or a short bio"
                    />
                  </label>
                </div>
              </div>

              <button type="submit" className="profile-submit">
                Save profile
              </button>
            </form>
          </div>
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════════
          SECTION 2 — Contribute Research (collapsible)
      ══════════════════════════════════════════════════════════════ */}
      <div className={`accordion ${contributeOpen ? "accordion--open" : ""}`}>
        <button
          type="button"
          className="accordion-trigger"
          onClick={() => setContributeOpen(!contributeOpen)}
          aria-expanded={contributeOpen}
        >
          <div className="accordion-trigger-left">
            <h2>Contribute research</h2>
            {!contributeOpen && queue.length > 0 && (
              <span className="accordion-preview accordion-preview--accent">
                {queue.length} paper{queue.length > 1 ? "s" : ""} queued
              </span>
            )}
            {!contributeOpen && queue.length === 0 && (
              <span className="accordion-preview">Add research notes for visitors</span>
            )}
          </div>
          <div className="accordion-trigger-right">
            <span className="accordion-badge">Scholar only</span>
            {queue.length > 0 && (
              <span className="accordion-count">{queue.length}</span>
            )}
            <span className={`accordion-chevron ${contributeOpen ? "accordion-chevron--open" : ""}`}>
              ▾
            </span>
          </div>
        </button>

        <div className="accordion-body">
          <div className="accordion-body-inner">
            <p className="contribution-intro">
              Add one or more research notes below. Fill in each paper and click
              <strong> "Add to queue"</strong> — then submit them all at once.
            </p>

            {/* ── Queued papers list ──────────────────────────────────── */}
            {queue.length > 0 && (
              <div className="paper-queue">
              <span className="profile-group-label">
                Queued papers · {queue.length}
              </span>
              <div className="paper-queue-list">
                {queue.map((entry, i) => (
                  <div
                    className={`paper-queue-card ${editingIndex === i ? "paper-queue-card--editing" : ""}`}
                    key={i}
                  >
                    <div className="paper-queue-card-body">
                      <strong className="paper-queue-title">{entry.title}</strong>
                      <div className="paper-queue-meta">
                        {entry.therapeutic_area && (
                          <span className="paper-queue-tag">{entry.therapeutic_area}</span>
                        )}
                        {entry.stage_of_research && (
                          <span className="paper-queue-tag">{entry.stage_of_research}</span>
                        )}
                        {entry.drug && (
                          <span className="paper-queue-tag paper-queue-tag--drug">{entry.drug}</span>
                        )}
                        {entry.disease && (
                          <span className="paper-queue-tag paper-queue-tag--disease">{entry.disease}</span>
                        )}
                      </div>
                      <p className="paper-queue-summary">
                        {entry.summary.slice(0, 120)}
                        {entry.summary.length > 120 ? "…" : ""}
                      </p>
                    </div>
                    <div className="paper-queue-actions">
                      <button
                        type="button"
                        className="paper-queue-btn paper-queue-btn--edit"
                        onClick={() => editEntry(i)}
                        title="Edit this entry"
                      >
                        ✎
                      </button>
                      <button
                        type="button"
                        className="paper-queue-btn paper-queue-btn--remove"
                        onClick={() => removeFromQueue(i)}
                        title="Remove from queue"
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              {/* Submit all — inside the queue area */}
              <button
                type="button"
                className="profile-submit paper-submit-all"
                onClick={submitAll}
                disabled={submitting}
              >
                {submitting
                  ? "Submitting…"
                  : `Submit ${queue.length} research note${queue.length > 1 ? "s" : ""}`}
              </button>
            </div>
          )}

          {/* ── Paper entry form ────────────────────────────────────── */}
          <form onSubmit={addToQueue} className="paper-entry-form">
            <span className="profile-group-label">
              {editingIndex !== null ? `Editing paper #${editingIndex + 1}` : "New paper"}
            </span>

            <label>
              Title
              <input
                value={draft.title}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                required
                placeholder="Describe the finding or observation"
              />
            </label>
            <div className="form-grid" style={{ marginTop: "var(--space-4)" }}>
              <label>
                Therapeutic Area
                <input
                  value={draft.therapeutic_area}
                  onChange={(e) => setDraft({ ...draft, therapeutic_area: e.target.value })}
                  placeholder="e.g., Oncology"
                />
              </label>
              <label>
                Stage of Research
                <select
                  value={draft.stage_of_research}
                  onChange={(e) => setDraft({ ...draft, stage_of_research: e.target.value })}
                >
                  <option value="">Select stage</option>
                  <option value="Pre-clinical">Pre-clinical</option>
                  <option value="Phase 1">Phase 1</option>
                  <option value="Phase 2">Phase 2</option>
                  <option value="Phase 3">Phase 3</option>
                  <option value="Post-market">Post-market</option>
                </select>
              </label>
            </div>

            <div style={{ marginTop: "var(--space-4)" }}>
              <label>
                Summary
                <textarea
                  className="textarea-tall"
                  value={draft.summary}
                  onChange={(e) => setDraft({ ...draft, summary: e.target.value })}
                  required
                  minLength={20}
                  placeholder="Describe the evidence and its limits. Do not include patient data."
                />
              </label>
            </div>

            <div className="profile-form-row" style={{ marginTop: "var(--space-4)" }}>
              <label>
                Drug (optional)
                <input
                  value={draft.drug}
                  onChange={(e) => setDraft({ ...draft, drug: e.target.value })}
                  placeholder="Drug name"
                />
              </label>
              <label>
                Disease (optional)
                <input
                  value={draft.disease}
                  onChange={(e) => setDraft({ ...draft, disease: e.target.value })}
                  placeholder="Disease or condition"
                />
              </label>
            </div>

            <div style={{ marginTop: "var(--space-4)" }}>
              <label className="label-code">
                Source link (optional)
                <input
                  type="url"
                  value={draft.source_url}
                  onChange={(e) => setDraft({ ...draft, source_url: e.target.value })}
                  placeholder="https://doi.org/..."
                />
              </label>
            </div>

            <div style={{ marginTop: "var(--space-4)" }}>
              <label>
                Collaboration Interests
                <textarea
                  value={draft.collaboration_interests}
                  onChange={(e) =>
                    setDraft({ ...draft, collaboration_interests: e.target.value })
                  }
                  placeholder="Describe the type of collaboration you are looking for"
                />
              </label>
            </div>

            <div className="paper-entry-actions">
              <button type="submit" className="profile-submit profile-submit--secondary">
                {editingIndex !== null ? "Update in queue" : "+ Add to queue"}
              </button>
              {editingIndex !== null && (
                <button
                  type="button"
                  className="paper-entry-cancel"
                  onClick={() => { setEditingIndex(null); setDraft({ ...EMPTY_RESEARCH }); }}
                >
                  Cancel edit
                </button>
              )}
            </div>
          </form>
          </div>
        </div>
      </div>

      {/* ── Feedback message ──────────────────────────────────────── */}
      {message && <p className="profile-success">{message}</p>}

      {/* ── Sign-out ──────────────────────────────────────────────── */}
      <div className="profile-logout-row">
        <button
          className="profile-logout"
          onClick={() => {
            logout();
            navigate("/");
          }}
        >
          Sign out of scholar account
        </button>
      </div>
    </section>
  );
}
