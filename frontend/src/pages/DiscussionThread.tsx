import { useEffect, useRef, useState } from "react";
import {
  getDiscussion,
  likeReply,
  likeThread,
  postReply,
  type DiscussionReply,
  type ThreadDetail,
} from "../api";
import { navigate } from "../router";

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
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function CategoryBadge({ category }: { category: string }) {
  const slug = category.toLowerCase().replace(/\s+/g, "-");
  return <span className={`disc-category-badge disc-cat-${slug}`}>{category}</span>;
}

interface LikeButtonProps {
  count: number;
  onLike: () => void;
  loading: boolean;
}

function LikeButton({ count, onLike, loading }: LikeButtonProps) {
  return (
    <button
      className="disc-like-btn"
      onClick={onLike}
      disabled={loading}
      title="Upvote"
    >
      <span className="disc-like-icon">▲</span>
      <span className="mono disc-like-count">{count}</span>
    </button>
  );
}

interface AuthorNameInputProps {
  value: string;
  onChange: (v: string) => void;
}

function AuthorNameInput({ value, onChange }: AuthorNameInputProps) {
  const stored = typeof window !== "undefined" ? localStorage.getItem("disc_author") ?? "" : "";
  useEffect(() => {
    if (stored && !value) onChange(stored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <input
      id="disc-author-name"
      className="form-input"
      placeholder="Your display name"
      value={value}
      maxLength={120}
      onChange={(e) => {
        onChange(e.target.value);
        localStorage.setItem("disc_author", e.target.value);
      }}
    />
  );
}

interface Props {
  threadId: number;
}

export default function DiscussionThread({ threadId }: Props) {
  const [thread, setThread] = useState<ThreadDetail | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  const [author, setAuthor] = useState("");
  const [replyBody, setReplyBody] = useState("");
  const [replying, setReplying] = useState(false);
  const [replyError, setReplyError] = useState("");
  const [likeError, setLikeError] = useState("");

  // Like loading states
  const [likeLoadingThread, setLikeLoadingThread] = useState(false);
  const [likeLoadingReply, setLikeLoadingReply] = useState<number | null>(null);

  const replyRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setStatus("loading");
    getDiscussion(threadId)
      .then((t) => {
        setThread(t);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, [threadId]);

  function handleLikeThread() {
    if (!thread) return;
    if (!author.trim()) {
      setLikeError("Enter your display name below before upvoting.");
      document.getElementById("disc-author-name")?.focus();
      return;
    }
    setLikeError("");
    setLikeLoadingThread(true);
    likeThread(thread.id, author.trim())
      .then((res) => {
        setThread((prev) => prev ? { ...prev, like_count: res.new_count } : prev);
      })
      .catch(() => setLikeError("Could not update the upvote. Please try again."))
      .finally(() => setLikeLoadingThread(false));
  }

  function handleLikeReply(replyId: number) {
    if (!author.trim()) {
      setLikeError("Enter your display name below before upvoting.");
      document.getElementById("disc-author-name")?.focus();
      return;
    }
    setLikeError("");
    setLikeLoadingReply(replyId);
    likeReply(replyId, author.trim())
      .then((res) => {
        setThread((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            replies: prev.replies.map((r) =>
              r.id === replyId ? { ...r, like_count: res.new_count } : r
            ),
          };
        });
      })
      .catch(() => setLikeError("Could not update the upvote. Please try again."))
      .finally(() => setLikeLoadingReply(null));
  }

  function handleReply(e: React.FormEvent) {
    e.preventDefault();
    setReplyError("");
    if (!author.trim()) { setReplyError("Please enter your display name."); return; }
    if (!replyBody.trim()) { setReplyError("Reply cannot be empty."); return; }
    setReplying(true);
    postReply(threadId, { body: replyBody.trim(), author: author.trim() })
      .then((reply: DiscussionReply) => {
        setThread((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            replies: [...prev.replies, reply],
            reply_count: prev.reply_count + 1,
            last_activity_at: reply.created_at,
          };
        });
        setReplyBody("");
        localStorage.setItem("disc_author", author.trim());
      })
      .catch(() => setReplyError("Failed to post reply — please try again."))
      .finally(() => setReplying(false));
  }

  if (status === "loading") return <div className="page empty-state">Loading discussion…</div>;
  if (status === "error" || !thread)
    return (
      <div className="page empty-state">
        Couldn't load this thread.{" "}
        <button className="tab" onClick={() => navigate("/discussions")}>← Back to Community</button>
      </div>
    );

  return (
    <div className="page page-full disc-thread-page">
      {/* Breadcrumb */}
      <div className="disc-thread-breadcrumb">
        <button className="tab" onClick={() => navigate("/discussions")}>
          ← Research Community
        </button>
      </div>

      {/* Thread header */}
      <div className="disc-thread-header">
        {/* Context banner */}
        {(thread.drug_name || thread.disease_name) && (
          <div className="disc-thread-context-banner">
            {thread.drug_name && (
              <button
                className="disc-context-link"
                onClick={() => navigate(`/drugs/${encodeURIComponent(thread.drug_name!)}`)}
              >
                {thread.drug_name}
              </button>
            )}
            {thread.drug_name && thread.disease_name && (
              <span className="disc-thread-context-arrow">→</span>
            )}
            {thread.disease_name && (
              <span className="disc-context-disease">{thread.disease_name}</span>
            )}
            <span className="disc-context-label">Research Signal Discussion</span>
          </div>
        )}

        <h1 className="disc-thread-title-h1">{thread.title}</h1>

        <div className="disc-thread-header-meta">
          <CategoryBadge category={thread.category} />
          <span className="disc-thread-author">by <strong>{thread.author}</strong></span>
          <span className="disc-thread-dot">·</span>
          <span className="disc-thread-date">{relativeTime(thread.created_at)}</span>
          <span className="disc-thread-dot">·</span>
          <span className="disc-stat-inline mono">{thread.reply_count} replies</span>
          <span className="disc-thread-dot">·</span>
          <span className="disc-stat-inline mono">{thread.like_count} upvotes</span>
        </div>
      </div>

      {/* Thread body */}
      <div className="disc-post disc-post-original">
        <div className="disc-post-avatar">
          <span className="disc-avatar-initial">{thread.author.charAt(0).toUpperCase()}</span>
        </div>
        <div className="disc-post-content">
          <div className="disc-post-author-row">
            <strong className="disc-post-author">{thread.author}</strong>
            <span className="disc-post-time">{relativeTime(thread.created_at)}</span>
          </div>
          <div className="disc-post-body">{thread.body}</div>
          <div className="disc-post-actions">
            <LikeButton
              count={thread.like_count}
              onLike={handleLikeThread}
              loading={likeLoadingThread}
            />
            <button
              className="disc-reply-action"
              onClick={() => replyRef.current?.focus()}
            >
              Reply
            </button>
          </div>
          {likeError && <div className="disc-form-error disc-like-error">{likeError}</div>}
        </div>
      </div>

      {/* Divider */}
      {thread.replies.length > 0 && (
        <div className="disc-replies-header">
          <span className="disc-replies-count mono">{thread.replies.length} {thread.replies.length === 1 ? "reply" : "replies"}</span>
        </div>
      )}

      {/* Replies */}
      <div className="disc-replies-list">
        {thread.replies.map((reply, idx) => (
          <div key={reply.id} className="disc-post disc-post-reply">
            <div className="disc-post-avatar">
              <span className="disc-avatar-initial">{reply.author.charAt(0).toUpperCase()}</span>
            </div>
            <div className="disc-post-content">
              <div className="disc-post-author-row">
                <strong className="disc-post-author">{reply.author}</strong>
                <span className="disc-post-time">{relativeTime(reply.created_at)}</span>
                <span className="disc-reply-index mono">#{idx + 1}</span>
              </div>
              <div className="disc-post-body">{reply.body}</div>
              <div className="disc-post-actions">
                <LikeButton
                  count={reply.like_count}
                  onLike={() => handleLikeReply(reply.id)}
                  loading={likeLoadingReply === reply.id}
                />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Reply compose */}
      <div className="disc-compose-section">
        <div className="disc-compose-header">
          <span className="detail-section-label">Add your reply</span>
          <span className="disc-compose-note">
            {!author.trim() && "Set your display name to upvote or reply."}
          </span>
        </div>
        <form className="disc-compose-form" onSubmit={handleReply}>
          <label className="filter-field disc-author-field">
            Display name
            <AuthorNameInput value={author} onChange={setAuthor} />
          </label>
          <label className="filter-field disc-body-field">
            Reply
            <textarea
              ref={replyRef}
              id="disc-reply-body"
              className="form-input disc-textarea"
              placeholder="Share your research insight, question, or follow-up…"
              value={replyBody}
              onChange={(e) => setReplyBody(e.target.value)}
              rows={5}
            />
          </label>
          {replyError && <div className="disc-form-error">{replyError}</div>}
          <div className="disc-compose-actions">
            <button
              id="disc-post-reply-btn"
              type="submit"
              className="btn btn-primary"
              disabled={replying || !author.trim() || !replyBody.trim()}
            >
              {replying ? "Posting…" : "Post Reply"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
