"""Tests for check_iss_transits_for_nights scan-window coverage.

The observer is in PDT (-7), so the evening session for local date N spans
into UTC day N+1 (roughly UTC N+1 02:00-14:00). If the UTC scan window
only covers `days` UTC days starting at start_date, the session gets
missed entirely for single-night --alert use.
"""

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import astroplanner
from astroplanner import check_iss_transits_for_nights


class _FakeSkyfieldTime:
    """Minimal stand-in for skyfield's Time with utc_datetime()."""

    def __init__(self, dt_aware):
        self._dt = dt_aware

    def utc_datetime(self):
        return self._dt


def _make_event(utc_dt):
    return {
        "time": _FakeSkyfieldTime(utc_dt),
        "min_sep": 0.3,
        "moon_ang_radius": 0.25,
        "is_transit": True,
        "transit_duration_s": 1.0,
        "moon_alt": 45.0,
        "moon_az": 180.0,
        "moon_illum": 50.0,
        "iss_alt": 60.0,
    }


def test_pdt_session_transit_is_found_for_single_night():
    """A transit at UTC 08:00 April 24 is inside the April 23 PDT session.

    With TIMEZONE_OFFSET = -7, the April 23 evening session runs roughly
    April 24 02:00 UTC -> 14:00 UTC. check_iss_transits_for_nights(April 23, 1)
    must scan deeply enough to see this event and key it under April 23.
    """
    event_utc = datetime(2026, 4, 24, 8, 0, tzinfo=timezone.utc)

    def fake_find(start_date, days):
        scan_start = datetime(
            start_date.year, start_date.month, start_date.day,
            tzinfo=timezone.utc,
        )
        scan_end = datetime(
            start_date.year, start_date.month, start_date.day,
            tzinfo=timezone.utc,
        )
        # emulate find_iss_lunar_transits scanning [start_date, start_date+days)
        from datetime import timedelta
        scan_end = scan_start + timedelta(days=days)
        if scan_start <= event_utc < scan_end:
            return [_make_event(event_utc)]
        return []

    with patch.object(astroplanner, "find_iss_lunar_transits", side_effect=fake_find), \
         patch.object(astroplanner, "TIMEZONE_OFFSET", -7):
        result = check_iss_transits_for_nights(date(2026, 4, 23), 1)

    assert date(2026, 4, 23) in result, (
        f"expected April 23 session key, got {sorted(result.keys())}"
    )
    assert len(result[date(2026, 4, 23)]) == 1
    assert result[date(2026, 4, 23)][0]["is_transit"] is True


def test_pdt_session_transit_found_at_end_of_week():
    """Last session of a 7-day scan must also be covered.

    For days=7 on PDT, the session for April 29 runs into April 30 UTC
    morning. An event at April 30 08:00 UTC must appear under April 29.
    """
    event_utc = datetime(2026, 4, 30, 8, 0, tzinfo=timezone.utc)

    def fake_find(start_date, days):
        from datetime import timedelta
        scan_start = datetime(
            start_date.year, start_date.month, start_date.day,
            tzinfo=timezone.utc,
        )
        scan_end = scan_start + timedelta(days=days)
        if scan_start <= event_utc < scan_end:
            return [_make_event(event_utc)]
        return []

    with patch.object(astroplanner, "find_iss_lunar_transits", side_effect=fake_find), \
         patch.object(astroplanner, "TIMEZONE_OFFSET", -7):
        result = check_iss_transits_for_nights(date(2026, 4, 23), 7)

    assert date(2026, 4, 29) in result, (
        f"expected April 29 session key, got {sorted(result.keys())}"
    )
