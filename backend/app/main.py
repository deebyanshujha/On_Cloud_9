"""FastAPI backend (Step 8). Serves the signals already produced by Steps
3-6's ingestion + Step 5's comparison/scoring engine — no new
ingestion/comparison logic lives here, this is purely a read API over
what's already in `arbitrage.db`.

Signals are computed once at startup (there's no live re-polling yet —
that's the deferred Step 7) and held in memory, since recomputing a
~350-signal comparison per request would be pointless work for data that
doesn't change without re-running the ingestion scripts.

Run from backend/: uvicorn app.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.scoring import run_comparison
from app.ingestion.store import load_all_approved_indications, load_all_documents
from app.models.db import SessionLocal, init_db
from app.schemas.api import SignalOut, build_signal_out


def _compute_signals() -> list[SignalOut]:
    init_db()
    session = SessionLocal()
    try:
        documents = load_all_documents(session)
        approved = load_all_approved_indications(session)
    finally:
        session.close()

    signals = run_comparison(documents, approved)
    return [build_signal_out(s) for s in signals]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.signals = _compute_signals()
    yield


app = FastAPI(title="Biotech Arbitrage Engine API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/signals", response_model=list[SignalOut])
def list_signals(request: Request) -> list[SignalOut]:
    return request.app.state.signals


@app.get("/signals/{drug}", response_model=list[SignalOut])
def signals_for_drug(drug: str, request: Request) -> list[SignalOut]:
    normalized = drug.strip().lower()
    matches = [s for s in request.app.state.signals if s.drug == normalized]
    if not matches:
        raise HTTPException(status_code=404, detail=f"No signals found for drug '{drug}'")
    return matches


@app.get("/search", response_model=list[SignalOut])
def search(q: str, request: Request) -> list[SignalOut]:
    query = q.strip().lower()
    if not query:
        return []
    return [
        s
        for s in request.app.state.signals
        if query in s.drug or query in s.disease
    ]
