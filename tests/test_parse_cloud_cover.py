"""Tests for _parse_cloud_cover substring-ordering behavior."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from astroplanner import _parse_cloud_cover


def test_clear():
    assert _parse_cloud_cover("Clear") == 5


def test_sunny():
    assert _parse_cloud_cover("Sunny") == 5


def test_mostly_clear_not_treated_as_clear():
    assert _parse_cloud_cover("Mostly Clear") == 15


def test_mostly_sunny_not_treated_as_sunny():
    assert _parse_cloud_cover("Mostly Sunny") == 15


def test_partly_cloudy():
    assert _parse_cloud_cover("Partly Cloudy") == 45


def test_partly_sunny_not_treated_as_sunny():
    assert _parse_cloud_cover("Partly Sunny") == 45


def test_mostly_cloudy():
    assert _parse_cloud_cover("Mostly Cloudy") == 75


def test_cloudy():
    assert _parse_cloud_cover("Cloudy") == 90


def test_overcast():
    assert _parse_cloud_cover("Overcast") == 90


def test_fog():
    assert _parse_cloud_cover("Fog") == 85


def test_unknown_falls_back_to_50():
    assert _parse_cloud_cover("Thunderstorms") == 50


def test_case_insensitive():
    assert _parse_cloud_cover("MOSTLY CLEAR") == 15
    assert _parse_cloud_cover("partly sunny") == 45
