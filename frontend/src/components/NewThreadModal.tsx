import { useState } from "react";
import { createPortal } from "react-dom";
import {
  DISCUSSION_CATEGORIES,
  createDiscussion,
  type ThreadDetail,
} from "../api";

interface Props {
  initialDrug?: string;
  initialDisease?: string;
  initialSignalKey?: string;
  onClose: () => void;
  onCreated: (thread: ThreadDetail) => void;
}

export default function NewThreadModal({
  initialDrug,
  initialDisease,
  initialSignalKey,
  onClose,
  onCreated,
}: Props) {
  const storedAuthor = typeof window !== "undefined" ? localStorage.getItem("disc_author") ?? "" : "";

  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<string>(DISCUSSION_CATEGORIES[0]);
  const [body, setBody] = useState("");
  const [author, setAuthor] = useState(storedAuthor);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!title.trim() || title.trim().length < 4) {
      setError("Title must be at least 4 characters.");
      return;
    }
    if (!body.trim() || body.trim().length < 10) {
      setError("Body must be at least 10 characters.");
      return;
    }
    if (!author.trim()) {
      setError("Please enter your display name.");
      return;
    }
    setSubmitting(true);
    createDiscussion({
      title: title.trim(),
      category,
      body: body.trim(),
      author: author.trim(),
      drug_name: initialDrug ?? null,
      disease_name: initialDisease ?? null,
      signal_key: initialSignalKey ?? null,
    })
      .then((thread) => {
        localStorage.setItem("disc_author", author.trim());
        onCreated(thread);
      })
      .catch(() => setError("Failed to create thread — please try again."))
      .finally(() => setSubmitting(false));
  }

  const modal = (
    /* Backdrop */
    <div
      className="disc-modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label="New discussion thread"
    >
      <div className="disc-modal">
        {/* Header */}
        <div className="disc-modal-header">
          <h2 className="disc-modal-title">New Discussion Thread</h2>
          {(initialDrug || initialDisease) && (
            <div className="disc-modal-context">
              <span className="disc-context-label">Context: </span>
              {initialDrug && (
                <span className="disc-context-drug">{initialDrug}</span>
              )}
              {initialDrug && initialDisease && (
                <span className="disc-context-arrow">→</span>
              )}
              {initialDisease && (
                <span className="disc-context-disease">{initialDisease}</span>
              )}
            </div>
          )}
          <button
            className="disc-modal-close"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Form */}
        <form className="disc-modal-form" onSubmit={handleSubmit}>
          <label className="filter-field disc-modal-field">
            Display name <span className="disc-required">*</span>
            <input
              id="disc-new-author"
              className="form-input"
              placeholder="Your display name"
              value={author}
              maxLength={120}
              onChange={(e) => {
                setAuthor(e.target.value);
                localStorage.setItem("disc_author", e.target.value);
              }}
              required
            />
          </label>

          <label className="filter-field disc-modal-field">
            Category
            <select
              id="disc-new-category"
              className="form-input mono"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {DISCUSSION_CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>

          <label className="filter-field disc-modal-field">
            Title <span className="disc-required">*</span>
            <input
              id="disc-new-title"
              className="form-input"
              placeholder="e.g. Exploring metformin's potential in Alzheimer's — recent trial evidence"
              value={title}
              maxLength={280}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
            <span className="disc-char-count mono">{title.length}/280</span>
          </label>

          <label className="filter-field disc-modal-field">
            Discussion body <span className="disc-required">*</span>
            <textarea
              id="disc-new-body"
              className="form-input disc-textarea"
              placeholder="Share your research question, findings, or insight…"
              value={body}
              rows={7}
              onChange={(e) => setBody(e.target.value)}
              required
            />
          </label>

          {error && <div className="disc-form-error">{error}</div>}

          <div className="disc-modal-actions">
            <button
              type="button"
              className="tab"
              onClick={onClose}
              disabled={submitting}
            >
              Cancel
            </button>
            <button
              id="disc-new-submit-btn"
              type="submit"
              className="btn btn-primary"
              disabled={submitting}
            >
              {submitting ? "Posting…" : "Start Discussion"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );

  return typeof document === "undefined" ? null : createPortal(modal, document.body);
}
