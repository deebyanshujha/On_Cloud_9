"""Tests that pipeline limits are genuinely runtime-configurable via env
vars (Step 10's acceptance test: changing the scan limit takes effect with
zero code changes)."""
import importlib

from app.core import config as config_module


def test_defaults_when_no_env_vars_set(monkeypatch):
    monkeypatch.delenv("ARB_MAX_RESULTS_PER_SOURCE", raising=False)
    monkeypatch.delenv("ARB_TIME_WINDOW_DAYS", raising=False)
    monkeypatch.delenv("ARB_MIN_CONFIDENCE_SCORE", raising=False)
    reloaded = importlib.reload(config_module)

    assert reloaded.MAX_RESULTS_PER_SOURCE == 10
    assert reloaded.TIME_WINDOW_DAYS == 90
    assert reloaded.MIN_CONFIDENCE_SCORE == 0.0


def test_env_var_overrides_scan_limit(monkeypatch):
    monkeypatch.setenv("ARB_MAX_RESULTS_PER_SOURCE", "50")
    reloaded = importlib.reload(config_module)

    assert reloaded.MAX_RESULTS_PER_SOURCE == 50

    monkeypatch.delenv("ARB_MAX_RESULTS_PER_SOURCE", raising=False)
    importlib.reload(config_module)


def test_env_var_overrides_min_confidence(monkeypatch):
    monkeypatch.setenv("ARB_MIN_CONFIDENCE_SCORE", "0.5")
    reloaded = importlib.reload(config_module)

    assert reloaded.MIN_CONFIDENCE_SCORE == 0.5

    monkeypatch.delenv("ARB_MIN_CONFIDENCE_SCORE", raising=False)
    importlib.reload(config_module)
