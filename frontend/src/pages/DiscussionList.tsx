import { useEffect, useRef, useState } from "react";
import {
  DISCUSSION_CATEGORIES,
  listDiscussions,
  type DiscussionSortOrder,
  type ThreadSummary,
} from "../api";
import { navigate } from "../router";
import NewThreadModal from "../components/NewThreadModal";

function relativeTime(iso: string): string {
  const timestamp = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`;
  const diff = Date.now() - new Date(timestamp).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(timestamp).toLocaleDateString();
}

function CategoryBadge({ category }: { category: string }) {
  const slug = category.toLowerCase().replace(/\s+/g, "-");
  return <span className={`disc-category-badge disc-cat-${slug}`}>{category}</span>;
}

function ContextPill({ drug, disease }: { drug: string | null; disease: string | null }) {
  if (!drug && !disease) return null;
  return (
    <span className="disc-context-pill">
      {drug && <span className="disc-context-drug">{drug}</span>}
      {drug && disease && <span className="disc-context-arrow">→</span>}
      {disease && <span className="disc-context-disease">{disease}</span>}
    </span>
  );
}

interface ThreadRowProps {
  thread: ThreadSummary;
}

function ThreadRow({ thread }: ThreadRowProps) {
  return (
    <div
      className={`disc-thread-row ${thread.pinned ? "disc-thread-pinned" : ""}`}
      onClick={() => navigate(`/discussions/${thread.id}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && navigate(`/discussions/${thread.id}`)}
    >
      <div className="disc-thread-main">
        <div className="disc-thread-title-row">
          {thread.pinned && <span className="disc-pin-icon" title="Pinned">📌</span>}
          <span className="disc-thread-title">{thread.title}</span>
        </div>
        <div className="disc-thread-meta-row">
          <CategoryBadge category={thread.category} />
          <ContextPill drug={thread.drug_name} disease={thread.disease_name} />
          <span className="disc-thread-author">by {thread.author}</span>
          <span className="disc-thread-dot">·</span>
          <span className="disc-thread-date">{relativeTime(thread.created_at)}</span>
        </div>
      </div>

      <div className="disc-thread-stats">
        <div className="disc-stat" title="Replies">
          <span className="disc-stat-value mono">{thread.reply_count}</span>
          <span className="disc-stat-label">replies</span>
        </div>
        <div className="disc-stat disc-stat-likes" title="Upvotes">
          <span className="disc-stat-value mono">{thread.like_count}</span>
          <span className="disc-stat-label">upvotes</span>
        </div>
        <div className="disc-stat disc-stat-activity" title="Last activity">
          <span className="disc-stat-label">{relativeTime(thread.last_activity_at)}</span>
        </div>
      </div>
    </div>
  );
}

const SORT_OPTIONS: { value: DiscussionSortOrder; label: string }[] = [
  { value: "newest", label: "Newest" },
  { value: "active", label: "Most Active" },
  { value: "discussed", label: "Most Discussed" },
];

const DEBOUNCE_MS = 300;

interface Props {
  initialDrug?: string;
  initialDisease?: string;
  initialSignalKey?: string;
}

export default function DiscussionList({ initialDrug, initialDisease, initialSignalKey }: Props) {
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState<DiscussionSortOrder>("newest");
  const [offset, setOffset] = useState(0);
  const [showModal, setShowModal] = useState(false);

  // Context filters (passed in from drug/signal pages)
  const drugFilter = initialDrug ?? "";
  const diseaseFilter = initialDisease ?? "";
  const signalKeyFilter = initialSignalKey ?? "";

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const LIMIT = 30;

  function load(opts: { resetOffset?: boolean } = {}) {
    const newOffset = opts.resetOffset ? 0 : offset;
    if (opts.resetOffset) setOffset(0);
    setStatus("loading");
    listDiscussions({
      q: query,
      category,
      drug: drugFilter,
      disease: diseaseFilter,
      signal_key: signalKeyFilter,
      sort,
      limit: LIMIT,
      offset: newOffset,
    })
      .then((data) => {
        if (newOffset === 0) {
          setThreads(data.threads);
        } else {
          setThreads((prev) => [...prev, ...data.threads]);
        }
        setTotal(data.total);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }

  // On filter/sort change, debounce and reset
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => load({ resetOffset: true }), DEBOUNCE_MS);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, category, sort, drugFilter, diseaseFilter, signalKeyFilter]);

  const contextActive = !!(drugFilter || diseaseFilter || signalKeyFilter);

  return (
    <div className="page page-full">
      <div className="page-head disc-page-head">
        <div className="disc-page-title-area">
          <h1>Research Community</h1>
          <p className="page-subtitle">
            Discuss drug repurposing signals, clinical trial evidence, and emerging research with
            the scientific community.
          </p>
        </div>

        <button
          id="new-thread-btn"
          className="btn btn-primary disc-new-thread-btn"
          onClick={() => setShowModal(true)}
        >
          + New Discussion
        </button>
      </div>

      {/* Context banner — shown when navigating from drug/signal */}
      {contextActive && (
        <div className="disc-context-banner">
          <span className="disc-context-banner-label">Filtered by:</span>
          {drugFilter && <span className="disc-context-banner-chip disc-context-drug">{drugFilter}</span>}
          {drugFilter && diseaseFilter && <span className="disc-context-banner-arrow">→</span>}
          {diseaseFilter && <span className="disc-context-banner-chip disc-context-disease">{diseaseFilter}</span>}
          <button
            className="disc-context-banner-clear"
            onClick={() => navigate("/discussions")}
          >
            Clear filter ×
          </button>
        </div>
      )}

      {/* Controls */}
      <div className="disc-controls">
        <label className="platform-search disc-search-field">
          <span aria-hidden="true">⌕</span>
          <input
            id="disc-search-input"
            placeholder="Search discussions…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search discussions"
          />
        </label>

        <label className="filter-field">
          Category
          <select
            id="disc-category-filter"
            className="form-input mono"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">All categories</option>
            {DISCUSSION_CATEGORIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </label>

        <label className="filter-field">
          Sort
          <select
            id="disc-sort-select"
            className="form-input mono"
            value={sort}
            onChange={(e) => setSort(e.target.value as DiscussionSortOrder)}
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
      </div>

      {/* Thread list */}
      {status === "loading" && threads.length === 0 && (
        <div className="empty-state">Loading discussions…</div>
      )}
      {status === "error" && (
        <div className="empty-state">
          Couldn't load discussions — is the backend running?
        </div>
      )}

      {threads.length === 0 && status === "ready" && (
        <div className="empty-state disc-empty">
          <div className="disc-empty-icon">💬</div>
          <div>No discussions yet{category ? ` in "${category}"` : ""}{query ? ` matching "${query}"` : ""}.</div>
          <button className="btn btn-primary" onClick={() => setShowModal(true)}>
            Start the first discussion
          </button>
        </div>
      )}

      {threads.length > 0 && (
        <div className="disc-thread-list">
          {/* Column headers */}
          <div className="disc-thread-list-header">
            <span className="disc-col-topic">Topic</span>
            <span className="disc-col-stats">Replies · Upvotes · Activity</span>
          </div>
          {threads.map((t) => (
            <ThreadRow key={t.id} thread={t} />
          ))}
        </div>
      )}

      {/* Load more */}
      {status === "ready" && threads.length < total && (
        <div className="load-more-row">
          <button
            className="tab"
            onClick={() => {
              const newOffset = offset + LIMIT;
              setOffset(newOffset);
              load();
            }}
          >
            Load more ({threads.length} of {total})
          </button>
        </div>
      )}

      {/* New Thread modal */}
      {showModal && (
        <NewThreadModal
          initialDrug={drugFilter || undefined}
          initialDisease={diseaseFilter || undefined}
          initialSignalKey={signalKeyFilter || undefined}
          onClose={() => setShowModal(false)}
          onCreated={(thread) => {
            setShowModal(false);
            navigate(`/discussions/${thread.id}`);
          }}
        />
      )}
    </div>
  );
}
