"""Tests for the run_observe candidate-iteration loop.

The loop's if/elif chain handles every documented `_observe_target` return
value (`done`, `target_set`, `error`) with `break` or `continue`. An
unrecognized value should raise rather than silently fall through, so the
design intent ("every result is explicitly handled") survives future edits.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from astropy.time import Time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import astroplanner


class _StubScope:
    """Stand-in for SeestarTelescope -- only the calls run_observe makes."""

    def __init__(self, *args, **kwargs):
        pass

    def connect(self):
        pass

    def disconnect(self):
        pass

    def _get(self, device, num, prop, **extra):
        # `atpark` -> not parked, so the unpark path is skipped.
        return {"Value": False}

    def _put(self, device, num, action, **params):
        return {"ErrorNumber": 0}


def _make_candidate(name, hours_ahead):
    end = Time(datetime.now(timezone.utc) + timedelta(hours=hours_ahead))
    return {
        "name": name,
        "common": name,
        "window_end": end,
        "adjusted_score": 50.0,
    }


def _run_with_results(results, candidates=None):
    """Run run_observe with `_observe_target` returning successive `results`.

    Returns the list of target dicts passed to `_observe_target`.
    """
    if candidates is None:
        candidates = [_make_candidate("M1", 4.0), _make_candidate("M42", 4.0)]
    seen = []
    iter_results = iter(results)

    def fake_observe_target(scope, target, *args, **kwargs):
        seen.append(target)
        return next(iter_results)

    dark_start = Time(datetime.now(timezone.utc))
    dark_end = Time(datetime.now(timezone.utc) + timedelta(hours=4))

    with patch.object(astroplanner, "select_observe_targets",
                      return_value=(candidates, dark_start, dark_end)), \
         patch.object(astroplanner, "SeestarTelescope", _StubScope), \
         patch.object(astroplanner, "_observe_target",
                      side_effect=fake_observe_target), \
         patch.object(astroplanner, "_send_observe_email"), \
         patch.object(astroplanner, "_print_session_summary"):
        astroplanner.run_observe(
            location=None,
            start_date=datetime.now(timezone.utc).date(),
            min_alt=35,
            min_moon_sep=30,
            type_filter=None,
            lp_filter_mode="auto",
        )
    return seen


def test_done_ends_session_after_one_call():
    seen = _run_with_results(["done"])
    assert len(seen) == 1


def test_error_ends_session_after_one_call():
    seen = _run_with_results(["error"])
    assert len(seen) == 1


def test_target_set_attempts_fallback():
    # primary "target_set", then fallback "done" -> two calls on distinct
    # targets, in order.
    seen = _run_with_results(["target_set", "done"])
    assert [t["name"] for t in seen] == ["M1", "M42"]


def test_second_target_set_ends_session():
    # primary "target_set", then fallback "target_set" -> stop (fallback
    # already used). Exactly two calls.
    seen = _run_with_results(["target_set", "target_set"])
    assert len(seen) == 2


def test_target_set_with_no_viable_fallback_ends_session():
    # Only one candidate -> no fallback list to iterate -> single call.
    seen = _run_with_results(
        ["target_set"],
        candidates=[_make_candidate("M1", 4.0)],
    )
    assert len(seen) == 1


def test_unknown_result_raises_value_error():
    with pytest.raises(ValueError, match="unexpected"):
        _run_with_results(["unexpected"])
