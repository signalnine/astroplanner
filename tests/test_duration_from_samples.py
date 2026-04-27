"""Tests for _duration_from_samples -- linspace-aware duration helper.

linspace(0, T, N) returns N samples spanning N-1 equal intervals of width
T/(N-1). The helper converts an above-threshold sample count into a duration
using the correct spacing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from astroplanner import _duration_from_samples


def test_uses_n_minus_one_spacing():
    # 11 samples across T=10.0 -> 10 intervals of width 1.0.
    # 2 samples above threshold -> 2 * 1.0 = 2.0.
    assert _duration_from_samples(2, 10.0, 11) == 2.0


def test_single_sample_returns_zero():
    # n_samples == 1 would divide by zero with the (N-1) formula. Guard.
    assert _duration_from_samples(1, 5.0, 1) == 0.0


def test_zero_above_returns_zero():
    assert _duration_from_samples(0, 6.0, 36) == 0.0


def test_typical_dso_window_overcounts_old_formula():
    # Old formula: 36 * (6.0/36) = 6.0
    # New formula: 36 * (6.0/35) = 6.171...
    # The new value is ~2.86% larger -- matches the issue's claim.
    new_val = _duration_from_samples(36, 6.0, 36)
    old_val = 36 * (6.0 / 36)
    assert new_val > old_val
    assert abs(new_val / old_val - 36 / 35) < 1e-9


def test_iss_refine_window_typical():
    # ISS refinement: 20s window, n_fine=1000 (50 sample/s).
    # 50 samples above (1s of "transit"): old gives 50*20/1000=1.0,
    # new gives 50*20/999.
    new_val = _duration_from_samples(50, 20.0, 1000)
    assert abs(new_val - 50 * 20.0 / 999) < 1e-12


def test_two_samples_one_above_equals_full_span():
    # N=2 samples at endpoints, 1 above -> dt = T/(2-1) = T -> 1*T.
    assert _duration_from_samples(1, 3.0, 2) == 3.0
