"""Pydantic schemas for the Research Discussion / Community Threads API.

Naming follows the same conventions as schemas/case.py:
- *Create  — input shape for POST endpoints
- *Out     — response shape for individual records
- *Summary — lightweight list-view shape (no full body text)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---- Thread ----------------------------------------------------------------

class ThreadCreate(BaseModel):
    title: str = Field(min_length=4, max_length=280)
    category: str
    body: str = Field(min_length=10)
    author: str = Field(min_length=1, max_length=120)
    # Optional context from drug/signal/opportunity
    drug_name: Optional[str] = None
    disease_name: Optional[str] = None
    signal_key: Optional[str] = None


class ThreadSummaryOut(BaseModel):
    """Lightweight shape for the thread list — no full body to keep payloads small."""

    id: int
    title: str
    category: str
    author: str
    pinned: bool
    drug_name: Optional[str] = None
    disease_name: Optional[str] = None
    signal_key: Optional[str] = None
    reply_count: int
    like_count: int
    created_at: datetime
    last_activity_at: datetime


class ThreadOut(BaseModel):
    """Full thread shape including body text, returned for the detail view."""

    id: int
    title: str
    category: str
    body: str
    author: str
    pinned: bool
    drug_name: Optional[str] = None
    disease_name: Optional[str] = None
    signal_key: Optional[str] = None
    reply_count: int
    like_count: int
    created_at: datetime
    last_activity_at: datetime
    replies: list["ReplyOut"] = Field(default_factory=list)


# ---- Reply -----------------------------------------------------------------

class ReplyCreate(BaseModel):
    body: str = Field(min_length=2)
    author: str = Field(min_length=1, max_length=120)


class ReplyOut(BaseModel):
    id: int
    thread_id: int
    body: str
    author: str
    like_count: int
    created_at: datetime


# ---- Like ------------------------------------------------------------------

class LikeOut(BaseModel):
    target_type: str
    target_id: int
    liked: bool       # True = like was added, False = like was removed (toggle)
    new_count: int    # Current like count after the action


# ---- List ------------------------------------------------------------------

class ThreadListOut(BaseModel):
    threads: list[ThreadSummaryOut]
    total: int
    limit: int
    offset: int
