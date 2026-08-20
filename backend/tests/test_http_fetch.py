"""Tests for the shared retry/backoff/outcome-classification helper used
by every case-research HTTP source (Europe PMC, PubMed, ClinicalTrials.gov)
— see app/core/http_fetch.py. Uses a fake client (no real httpx.Client, no
network) so timeout/429/5xx/4xx paths are deterministic and fast.
"""
from __future__ import annotations

import httpx
import pytest

from app.core.http_fetch import get_with_retry


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", headers: dict | None = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class _ScriptedClient:
    """Fake httpx.Client stand-in: `.get()` pops the next scripted action
    off a list — either a _FakeResponse or an exception instance/class to
    raise — so each test can script exactly the failure sequence it wants
    without any real network I/O."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls = 0

    def get(self, url, params=None):
        self.calls += 1
        action = self.script.pop(0)
        if isinstance(action, Exception):
            raise action
        if isinstance(action, type) and issubclass(action, Exception):
            raise action("scripted failure")
        return action


def test_success_on_first_try_returns_response_no_retry():
    client = _ScriptedClient([_FakeResponse(200, text='{"ok":true}')])
    outcome = get_with_retry(client, "http://example", {}, max_retries=2, backoff_seconds=0)
    assert outcome.status == "success"
    assert outcome.response.status_code == 200
    assert outcome.attempts == 1
    assert client.calls == 1


def test_timeout_retries_then_succeeds():
    client = _ScriptedClient([httpx.TimeoutException("slow"), _FakeResponse(200)])
    outcome = get_with_retry(client, "http://example", {}, max_retries=2, backoff_seconds=0)
    assert outcome.status == "success"
    assert outcome.attempts == 2
    assert client.calls == 2


def test_timeout_exhausts_retries_and_reports_timeout_status():
    client = _ScriptedClient([httpx.TimeoutException("slow")] * 3)
    outcome = get_with_retry(client, "http://example", {}, max_retries=2, backoff_seconds=0)
    assert outcome.status == "timeout"
    assert outcome.error is not None
    assert client.calls == 3  # initial attempt + 2 retries


def test_server_error_5xx_retries_then_succeeds():
    client = _ScriptedClient([_FakeResponse(503, text="unavailable"), _FakeResponse(200)])
    outcome = get_with_retry(client, "http://example", {}, max_retries=2, backoff_seconds=0)
    assert outcome.status == "success"
    assert client.calls == 2


def test_server_error_5xx_exhausts_retries_reports_http_error():
    client = _ScriptedClient([_FakeResponse(500)] * 3)
    outcome = get_with_retry(client, "http://example", {}, max_retries=2, backoff_seconds=0)
    assert outcome.status == "http_error"


def test_client_error_4xx_is_never_retried():
    client = _ScriptedClient([_FakeResponse(404, text="not found")])
    outcome = get_with_retry(client, "http://example", {}, max_retries=3, backoff_seconds=0)
    assert outcome.status == "http_error"
    assert client.calls == 1  # no retry burned on a client error


def test_rate_limited_429_retries_then_succeeds():
    client = _ScriptedClient([_FakeResponse(429, headers={"Retry-After": "0"}), _FakeResponse(200)])
    outcome = get_with_retry(client, "http://example", {}, max_retries=2, backoff_seconds=0)
    assert outcome.status == "success"
    assert client.calls == 2


def test_rate_limited_429_exhausts_retries_reports_rate_limited():
    client = _ScriptedClient([_FakeResponse(429, headers={"Retry-After": "0"})] * 3)
    outcome = get_with_retry(client, "http://example", {}, max_retries=2, backoff_seconds=0)
    assert outcome.status == "rate_limited"


def test_generic_request_error_retries_then_gives_up():
    client = _ScriptedClient([httpx.ConnectError("boom")] * 3)
    outcome = get_with_retry(client, "http://example", {}, max_retries=2, backoff_seconds=0)
    assert outcome.status == "http_error"
    assert client.calls == 3
