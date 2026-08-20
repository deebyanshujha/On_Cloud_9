"""SQLAlchemy models for the Research Discussion / Community Threads feature.

All tables live in the same `arbitrage.db` used by the rest of the app — no
separate database. The schema follows the same patterns as case.py:
- Mapped columns with explicit types
- ForeignKey references to own tables (not to cases — discussions are
  context-linked via free-text drug/disease/signal fields, not FK constraints,
  so a discussion can survive a pipeline rebuild)
- server_default=func.now() for timestamps

Author identity is a free-text display name — no auth system exists.
Likes use (target_type, target_id, author) as a soft uniqueness key; since
there's no session/auth, this is best-effort deduplication.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


CATEGORIES = [
    "Drug Repurposing",
    "Clinical Trials",
    "Biomedical Research",
    "Drug Safety",
    "Research Opportunities",
    "General Discussion",
]


class DiscussionThread(Base):
    """One discussion thread in the research community area.

    Context links (drug_name, disease_name, signal_key) are free-text — they
    let the frontend filter threads relevant to a specific drug or drug→disease
    signal without creating fragile FK constraints against ingested data that
    can change between pipeline runs.
    """

    __tablename__ = "discussion_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, index=True)
    category: Mapped[str] = mapped_column(String, index=True)
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String, index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    # Optional context links — populated when a thread is created from a
    # drug/signal/opportunity context. Any or all may be null.
    drug_name: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    disease_name: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # e.g. "metformin→alzheimer's disease" — the compound signal key
    signal_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Denormalized reply count and like count — updated on write so
    # list-view queries don't need expensive JOINs. Small enough dataset
    # that consistency is easy to maintain.
    reply_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)


class DiscussionReply(Base):
    """One reply inside a discussion thread."""

    __tablename__ = "discussion_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("discussion_threads.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DiscussionLike(Base):
    """A single upvote on a thread or reply.

    target_type: 'thread' | 'reply'
    target_id:   the thread or reply id
    author:      free-text display name — best-effort dedup (no auth)
    """

    __tablename__ = "discussion_likes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String, index=True)  # 'thread' | 'reply'
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    author: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
