"""Tests for _session_midnight_utc — midnight local during the evening session."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from astroplanner import _session_midnight_utc


def test_pdt_session_midnight_is_next_day_0700_utc():
    # Session starting evening of April 23 PDT: midnight is April 24 00:00 PDT
    # = April 24 07:00 UTC (not April 23 07:00 UTC, which was the previous bug).
    t = _session_midnight_utc(date(2026, 4, 23), -7)
    assert t.utc.iso == "2026-04-24 07:00:00.000"


def test_pst_session_midnight_respects_tz_offset():
    # Midnight PST = 08:00 UTC, not 07:00.
    t = _session_midnight_utc(date(2026, 4, 23), -8)
    assert t.utc.iso == "2026-04-24 08:00:00.000"


def test_utc_zero_offset():
    t = _session_midnight_utc(date(2026, 4, 23), 0)
    assert t.utc.iso == "2026-04-24 00:00:00.000"


def test_positive_offset_rolls_utc_day_back():
    # Local +5: midnight April 24 local = April 23 19:00 UTC.
    t = _session_midnight_utc(date(2026, 4, 23), 5)
    assert t.utc.iso == "2026-04-23 19:00:00.000"


def test_month_boundary():
    # Session starting April 30 PDT: midnight is May 1 07:00 UTC.
    t = _session_midnight_utc(date(2026, 4, 30), -7)
    assert t.utc.iso == "2026-05-01 07:00:00.000"


def test_year_boundary():
    # Session starting Dec 31 PST: midnight is Jan 1 08:00 UTC.
    t = _session_midnight_utc(date(2025, 12, 31), -8)
    assert t.utc.iso == "2026-01-01 08:00:00.000"
